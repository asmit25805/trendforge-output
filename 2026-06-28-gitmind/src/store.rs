use std::collections::HashMap;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use git2::{Commit, IndexAddOption, ObjectType, Oid, Repository, Signature};
use log::{error, info, warn};
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use uuid::Uuid;

/// Stable identifier derived from file path and commit hash.
pub type ArtifactId = String;

/// Front‑matter metadata for a markdown document.
#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct DocumentMeta {
    /// Optional title extracted from front‑matter or first heading.
    pub title: Option<String>,
    /// Arbitrary key‑value pairs.
    #[serde(flatten)]
    pub extra: HashMap<String, String>,
}

/// Core document representation stored in the knowledge base.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Document {
    /// Stable identifier – `<path>@<commit>`.
    pub id: ArtifactId,
    /// Relative path inside the repository.
    pub path: PathBuf,
    /// Raw markdown content.
    pub content: String,
    /// Parsed front‑matter.
    pub metadata: DocumentMeta,
}

/// Represents a single change to be applied to the store.
#[derive(Debug, Clone)]
pub struct DocumentChange {
    /// The document after the change.
    pub document: Document,
}

impl DocumentChange {
    /// Create a new change from a document.
    pub fn new(document: Document) -> Self {
        Self { document }
    }
}

/// Link between two artifacts.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Link {
    /// Source artifact identifier.
    pub source_id: ArtifactId,
    /// Target artifact identifier.
    pub target_id: ArtifactId,
    /// Optional anchor (heading or block identifier).
    pub anchor: Option<String>,
}

/// Errors that can arise from store operations.
#[derive(Error, Debug)]
pub enum StoreError {
    #[error("git error: {0}")]
    Git(#[from] git2::Error),

    #[error("io error: {0}")]
    Io(#[from] io::Error),

    #[error("validation error: {0}")]
    Validation(String),

    #[error("transient error: {0}")]
    Transient(String),

    #[error("fatal error: {0}")]
    Fatal(String),
}

/// In‑memory representation of the knowledge store.
pub struct KnowledgeStore {
    /// Path to the repository root.
    repo_path: PathBuf,
    /// Underlying git repository.
    repo: Repository,
    /// Cache of outgoing links per document.
    outgoing_links: Arc<std::sync::Mutex<HashMap<ArtifactId, Vec<Link>>>>,
}

impl KnowledgeStore {
    /// Initialise a store backed by a git repository at `repo_path`.
    pub fn new<P: AsRef<Path>>(repo_path: P) -> Result<Self, StoreError> {
        let repo_path = repo_path.as_ref().to_path_buf();
        let repo = match Repository::open(&repo_path) {
            Ok(r) => r,
            Err(_) => {
                info!("Git repository not found at {:?}, initializing new repo", repo_path);
                Repository::init(&repo_path)?
            }
        };
        Ok(Self {
            repo_path,
            repo,
            outgoing_links: Arc::new(std::sync::Mutex::new(HashMap::new())),
        })
    }

    /// Read the latest committed version of a document, including any uncommitted changes.
    pub fn read_doc<P: AsRef<Path>>(&self, path: P) -> Result<Document, StoreError> {
        let rel_path = path.as_ref();
        let head = self.repo.head()?.peel_to_commit()?;
        let tree = head.tree()?;
        let entry = tree.get_path(rel_path).map_err(|_| {
            StoreError::Validation(format!(
                "document '{}' does not exist in the repository",
                rel_path.display()
            ))
        })?;
        let blob = entry.to_object(&self.repo)?.peel_to_blob()?;
        let content = std::str::from_utf8(blob.content())
            .map_err(|e| StoreError::Fatal(format!("utf8 error: {}", e)))?
            .to_string();

        // Simple front‑matter extraction (YAML between --- delimiters).
        let (metadata, body) = Self::extract_front_matter(&content);
        let id = format!("{}@{}", rel_path.display(), head.id());

        Ok(Document {
            id,
            path: rel_path.to_path_buf(),
            content: body.to_string(),
            metadata,
        })
    }

    /// Write a document to the repository, creating a new commit.
    ///
    /// Returns the SHA‑1 hash of the new commit.
    pub fn write_doc(&self, doc: &Document) -> Result<String, StoreError> {
        // Stage the file.
        let mut index = self.repo.index()?;
        let full_path = self.repo_path.join(&doc.path);
        fs::create_dir_all(full_path.parent().ok_or_else(|| {
            StoreError::Validation(format!("invalid document path '{}'", doc.path.display()))
        })?)?;
        let mut file = fs::File::create(&full_path)?;
        file.write_all(doc.content.as_bytes())?;
        file.flush()?;

        index.add_path(&doc.path)?;
        index.write()?;

        // Create commit.
        let tree_id = index.write_tree()?;
        let tree = self.repo.find_tree(tree_id)?;
        let parent_commit = match self.repo.head() {
            Ok(head) => Some(head.peel_to_commit()?),
            Err(_) => None,
        };
        let sig = Signature::now("gitmind", "gitmind@example.com")?;
        let commit_msg = format!("Update {}", doc.path.display());
        let commit_oid = match parent_commit {
            Some(parent) => self.repo.commit(
                Some("HEAD"),
                &sig,
                &sig,
                &commit_msg,
                &tree,
                &[&parent],
            )?,
            None => self.repo.commit(
                Some("HEAD"),
                &sig,
                &sig,
                &commit_msg,
                &tree,
                &[],
            )?,
        };
        let commit_hash = commit_oid.to_string();

        // Update caches.
        let outgoing = Self::parse_links(&doc);
        {
            let mut cache = self.outgoing_links.lock().unwrap();
            cache.insert(doc.id.clone(), outgoing);
        }

        info!(
            "Committed document '{}' as {} ({} bytes)",
            doc.path.display(),
            commit_hash,
            doc.content.len()
        );
        Ok(commit_hash)
    }

    /// List all backlinks that point to `target_id`.
    ///
    /// This walks the cached outgoing links of all documents and returns those where
    /// `target_id` appears as a target.
    pub fn list_backlinks(&self, target_id: &ArtifactId) -> Result<Vec<Link>, StoreError> {
        let cache = self.outgoing_links.lock().unwrap();
        let mut backlinks = Vec::new();
        for (source_id, links) in cache.iter() {
            for link in links {
                if &link.target_id == target_id {
                    backlinks.push(Link {
                        source_id: source_id.clone(),
                        target_id: link.target_id.clone(),
                        anchor: link.anchor.clone(),
                    });
                }
            }
        }
        Ok(backlinks)
    }

    /// Parse markdown content for link patterns and produce a vector of `Link`.
    fn parse_links(doc: &Document) -> Vec<Link> {
        let link_regex = Regex::new(r"\[.*?\]\(([^)#?]+)(#[^\s)]*)?\)").unwrap();
        let mut links = Vec::new();

        for cap in link_regex.captures_iter(&doc.content) {
            let target_path = cap.get(1).map(|m| m.as_str()).unwrap_or_default();
            let anchor = cap.get(2).map(|m| m.as_str().trim_start_matches('#').to_string());

            // Resolve target artifact id as `<path>@<head>`
            // For simplicity we use the path itself; the caller can resolve to a concrete id.
            let target_id = target_path.to_string();

            links.push(Link {
                source_id: doc.id.clone(),
                target_id,
                anchor,
            });
        }
        links
    }

    /// Extract front‑matter (YAML) from the beginning of a markdown document.
    ///
    /// Returns a tuple `(metadata, body_without_front_matter)`.
    fn extract_front_matter(content: &str) -> (DocumentMeta, &str) {
        let delimiter = "---";
        let mut lines = content.lines();
        if let Some(first) = lines.next() {
            if first.trim() == delimiter {
                let mut yaml = String::new();
                for line in &mut lines {
                    if line.trim() == delimiter {
                        break;
                    }
                    yaml.push_str(line);
                    yaml.push('\n');
                }
                let meta: DocumentMeta = serde_yaml::from_str(&yaml).unwrap_or_default();
                let body = lines.collect::<Vec<_>>().join("\n");
                return (meta, body.as_str());
            }
        }
        (DocumentMeta::default(), content)
    }

    /// Count tokens (approximate words) in a document's content.
    pub fn token_count(&self, doc: &Document) -> usize {
        doc.content.split_whitespace().count()
    }

    /// Helper to differentiate fatal vs transient git errors.
    fn classify_git_error(err: git2::Error) -> StoreError {
        if err.code() == git2::ErrorCode::Locked {
            StoreError::Transient(err.message().to_string())
        } else {
            StoreError::Fatal(err.message().to_string())
        }
    }

    /// Recompute outgoing links for a document after a change.
    ///
    /// This is called internally after `write_doc`.
    fn recompute_outgoing(&self, doc: &Document) -> Result<(), StoreError> {
        let links = Self::parse_links(doc);
        let mut cache = self.outgoing_links.lock().unwrap();
        cache.insert(doc.id.clone(), links);
        Ok(())
    }
}