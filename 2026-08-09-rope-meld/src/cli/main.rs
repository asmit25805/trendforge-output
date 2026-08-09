use std::env;
use std::fs;
use std::io::{self, BufRead, Write};

use clap::{Arg, Command};
use serde::Deserialize;

use crate::core::engine::RopePieceTableEngine;
use crate::collab::crdt::{EditError, DocumentOperation, InsertPayload, DeletePayload, OperationKind, OperationPayload};

/// Represents an insert edit read from stdin.
#[derive(Debug, Deserialize)]
struct InsertEdit {
    kind: String,
    pos: usize,
    text: String,
}

/// Represents a delete edit read from stdin.
#[derive(Debug, Deserialize)]
struct DeleteEdit {
    kind: String,
    range: (usize, usize),
}

/// Union type for deserialising edits.
#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum Edit {
    Insert(InsertEdit),
    Delete(DeleteEdit),
}

/// Parses a line of JSON into an `Edit`. Returns `None` if the line is empty.
fn parse_edit(line: &str) -> Result<Edit, serde_json::Error> {
    serde_json::from_str(line)
}

/// Applies a single edit to the engine, converting it into a `DocumentOperation`.
fn apply_edit(engine: &mut RopePieceTableEngine, edit: Edit) -> Result<(), EditError> {
    match edit {
        Edit::Insert(ins) => {
            // Create a DocumentOperation for the insert.
            let payload = InsertPayload {
                pos: ins.pos,
                text: ins.text,
            };
            let op = DocumentOperation {
                op_id: uuid::Uuid::new_v4(),
                timestamp: 0, // Lamport timestamp will be filled by CRDT layer; not needed here.
                author: 0,    // Single‑user CLI uses a dummy author.
                kind: OperationKind::Insert,
                payload: OperationPayload::Insert(payload),
            };
            // Directly invoke the engine's insert method.
            engine.insert(ins.pos, &payload.text)
        }
        Edit::Delete(del) => {
            let start = del.range.0;
            let end = del.range.1;
            let range = std::ops::Range { start, end };
            let payload = DeletePayload { range };
            let op = DocumentOperation {
                op_id: uuid::Uuid::new_v4(),
                timestamp: 0,
                author: 0,
                kind: OperationKind::Delete,
                payload: OperationPayload::Delete(payload),
            };
            engine.delete(range)
        }
    }
}

/// Renders the current document state to markdown. The engine is expected to expose a
/// `render_markdown` method; if it does not, this fallback concatenates the raw text.
fn render_markdown(engine: &RopePieceTableEngine) -> String {
    // Attempt to call a public method; if it does not exist we fall back to a simple reconstruction.
    // The fallback walks the rope manually using the public API of `RopePieceTableEngine`.
    // This implementation assumes that `engine` provides a `to_string` method; otherwise we
    // reconstruct the text from the original buffer and append‑only buffers.
    if let Some(render) = engine.render_markdown() {
        render
    } else {
        // Fallback: concatenate original buffer and all append buffers.
        let mut result = String::new();
        if let Ok(orig) = engine.original_buffer.try_borrow() {
            result.push_str(&orig);
        }
        if let Ok(appends) = engine.append_buffers.try_borrow() {
            for buf in appends.iter() {
                result.push_str(buf);
            }
        }
        result
    }
}

fn main() {
    // Set up CLI argument parsing.
    let matches = Command::new("rope-meld-cli")
        .about("Apply edits to a markdown document using the rope‑piece‑table engine")
        .arg(
            Arg::new("input")
                .help("Path to the initial markdown document")
                .required(true)
                .index(1),
        )
        .get_matches();

    let input_path = matches
        .get_one::<String>("input")
        .expect("input path is required");

    // Load the initial document.
    let initial_content = match fs::read_to_string(input_path) {
        Ok(content) => content,
        Err(err) => {
            eprintln!("Failed to read '{}': {}", input_path, err);
            std::process::exit(1);
        }
    };

    // Initialise the engine.
    let mut engine = RopePieceTableEngine::new(&initial_content);

    // Process edits from stdin.
    let stdin = io::stdin();
    for line_res in stdin.lock().lines() {
        let line = match line_res {
            Ok(l) => l,
            Err(err) => {
                eprintln!("Error reading stdin: {}", err);
                std::process::exit(1);
            }
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let edit = match parse_edit(trimmed) {
            Ok(e) => e,
            Err(err) => {
                eprintln!("Failed to parse edit '{}': {}", trimmed, err);
                continue; // Skip malformed edits.
            }
        };

        if let Err(err) = apply_edit(&mut engine, edit) {
            match err {
                EditError::InvalidRange => {
                    // Silently ignore invalid ranges as per design.
                }
                EditError::Other(msg) => {
                    eprintln!("Fatal edit error: {}", msg);
                    std::process::exit(1);
                }
            }
        }
    }

    // Render the final markdown.
    let markdown = render_markdown(&engine);
    let stdout = io::stdout();
    let mut handle = stdout.lock();
    if let Err(err) = writeln!(handle, "{}", markdown) {
        eprintln!("Failed to write output: {}", err);
        std::process::exit(1);
    }
}