use std::ops::Range;
use std::rc::Rc;
use std::cell::RefCell;

use rope::Rope;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use uuid::Uuid;

use crate::collab::crdt::{
    DocumentOperation, EditError, InsertPayload, DeletePayload, OperationKind, SyncError,
};

/// Identifier for a buffer. `0` is the original buffer, `1..` are append‑only buffers.
pub type BufferId = u8;

/// Inline formatting attribute (e.g., bold, italic, link). Extend as needed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Attribute {
    pub kind: String,
    pub value: Option<String>,
}

/// A piece of text referencing a buffer slice and optional formatting attributes.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Piece {
    pub buffer_id: BufferId,
    pub offset: usize,
    pub length: usize,
    pub attributes: Vec<Attribute>,
}

impl Piece {
    fn new(buffer_id: BufferId, offset: usize, length: usize) -> Self {
        Self {
            buffer_id,
            offset,
            length,
            attributes: Vec::new(),
        }
    }
}

/// Node of the balanced binary rope. Leaves contain a `Piece`; internal nodes only cache length.
#[derive(Debug, Clone)]
pub struct RopeNode {
    left: Option<Box<RopeNode>>,
    right: Option<Box<RopeNode>>,
    piece: Option<Piece>,
    subtree_len: usize,
}

impl RopeNode {
    fn leaf(piece: Piece) -> Self {
        let len = piece.length;
        Self {
            left: None,
            right: None,
            piece: Some(piece),
            subtree_len: len,
        }
    }

    fn internal(left: RopeNode, right: RopeNode) -> Self {
        let len = left.subtree_len + right.subtree_len;
        Self {
            left: Some(Box::new(left)),
            right: Some(Box::new(right)),
            piece: None,
            subtree_len: len,
        }
    }

    fn is_leaf(&self) -> bool {
        self.piece.is_some()
    }

    /// Recalculates the cached length; used after mutations.
    fn recalc(&mut self) {
        self.subtree_len = match (&self.left, &self.right, &self.piece) {
            (Some(l), Some(r), None) => l.subtree_len + r.subtree_len,
            (None, None, Some(p)) => p.length,
            _ => 0,
        };
    }
}

/// Core mutable document model backed by a piece‑table rope.
pub struct RopePieceTableEngine {
    /// Original immutable buffer (index 0).
    original_buffer: Rc<RefCell<String>>,
    /// Append‑only buffers; each new insert creates a new entry.
    append_buffers: Rc<RefCell<Vec<String>>>,
    /// Root of the rope indexing pieces.
    root: Option<Box<RopeNode>>,
}

impl RopePieceTableEngine {
    /// Creates a new engine from an initial string.
    pub fn new(initial: &str) -> Self {
        let original = Rc::new(RefCell::new(initial.to_string()));
        let root = if !initial.is_empty() {
            let piece = Piece::new(0, 0, initial.chars().count());
            Some(Box::new(RopeNode::leaf(piece)))
        } else {
            None
        };
        Self {
            original_buffer: original,
            append_buffers: Rc::new(RefCell::new(Vec::new())),
            root,
        }
    }

    /// Returns the total length of the document in characters.
    pub fn len(&self) -> usize {
        self.root.as_ref().map_or(0, |n| n.subtree_len)
    }

    /// Inserts `text` at byte offset `pos`. Returns `EditError::InvalidRange` on out‑of‑range.
    pub fn insert(&mut self, pos: usize, text: &str) -> Result<(), EditError> {
        let total_len = self.len();
        if pos > total_len {
            return Err(EditError::InvalidRange);
        }

        // Append text to the append‑only buffer and create a piece.
        let mut buffers = self.append_buffers.borrow_mut();
        let buffer_id = (buffers.len() + 1) as BufferId; // 0 is original
        let offset = buffers.iter().map(|b| b.len()).sum::<usize>();
        buffers.push(text.to_string());

        let piece = Piece::new(buffer_id, offset, text.chars().count());

        // Split the rope at `pos` and insert the new leaf.
        let (left, right) = self.split(self.root.take(), pos)?;
        let new_node = RopeNode::leaf(piece);
        let merged = Self::merge_nodes(left, Some(Box::new(new_node)), right);
        self.root = merged;
        Ok(())
    }

    /// Deletes the range `[range.start, range.end)`. Returns `EditError::InvalidRange` on bad range.
    pub fn delete(&mut self, range: Range<usize>) -> Result<(), EditError> {
        let total_len = self.len();
        if range.start > range.end || range.end > total_len {
            return Err(EditError::InvalidRange);
        }

        // Split into three parts: before, to‑delete, after.
        let (left, middle) = self.split(self.root.take(), range.start)?;
        let (_, right) = self.split(middle, range.end - range.start)?;
        // Discard `middle` and merge left & right.
        self.root = Self::merge_nodes(left, None, right);
        Ok(())
    }

    /// Applies a `DocumentOperation` generated by the CRDT layer.
    pub fn apply(&mut self, op: DocumentOperation) -> Result<(), EditError> {
        match op.kind {
            OperationKind::Insert => {
                let payload: InsertPayload = op.payload.try_into().map_err(|_| EditError::InvalidRange)?;
                self.insert(payload.position, &payload.text)
            }
            OperationKind::Delete => {
                let payload: DeletePayload = op.payload.try_into().map_err(|_| EditError::InvalidRange)?;
                self.delete(payload.range)
            }
        }
    }

    /// Splits the rope at `pos` characters, returning `(left, right)`.
    fn split(
        &self,
        node: Option<Box<RopeNode>>,
        pos: usize,
    ) -> Result<(Option<Box<RopeNode>>, Option<Box<RopeNode>>), EditError> {
        match node {
            None => Ok((None, None)),
            Some(mut n) => {
                if n.is_leaf() {
                    let piece = n.piece.take().unwrap();
                    if pos == 0 {
                        Ok((None, Some(Box::new(RopeNode::leaf(piece)))))
                    } else if pos >= piece.length {
                        Ok((Some(Box::new(RopeNode::leaf(piece))), None))
                    } else {
                        // Split the piece into two.
                        let left_piece = Piece::new(
                            piece.buffer_id,
                            piece.offset,
                            pos,
                        );
                        let right_piece = Piece::new(
                            piece.buffer_id,
                            piece.offset + pos,
                            piece.length - pos,
                        );
                        let left_node = RopeNode::leaf(left_piece);
                        let right_node = RopeNode::leaf(right_piece);
                        Ok((Some(Box::new(left_node)), Some(Box::new(right_node))))
                    }
                } else {
                    let left_len = n.left.as_ref().map_or(0, |l| l.subtree_len);
                    if pos < left_len {
                        let (l, r) = self.split(n.left.take(), pos)?;
                        let new_right = Self::merge_nodes(r, n.right.take(), None);
                        Ok((l, new_right))
                    } else {
                        let (l, r) = self.split(n.right.take(), pos - left_len)?;
                        let new_left = Self::merge_nodes(n.left.take(), None, l);
                        Ok((new_left, r))
                    }
                }
            }
        }
    }

    /// Merges optional left, middle, and right nodes into a balanced tree.
    fn merge_nodes(
        left: Option<Box<RopeNode>>,
        middle: Option<Box<RopeNode>>,
        right: Option<Box<RopeNode>>,
    ) -> Option<Box<RopeNode>> {
        // Simple heuristic: concatenate in order, then rebalance via recursion.
        let mut nodes = Vec::new();
        if let Some(l) = left {
            nodes.push(l);
        }
        if let Some(m) = middle {
            nodes.push(m);
        }
        if let Some(r) = right {
            nodes.push(r);
        }
        Self::build_balanced(nodes)
    }

    /// Builds a balanced binary tree from a vector of nodes.
    fn build_balanced(mut nodes: Vec<Box<RopeNode>>) -> Option<Box<RopeNode>> {
        fn build(mut list: &[Box<RopeNode>]) -> Option<Box<RopeNode>> {
            if list.is_empty() {
                return None;
            }
            if list.len() == 1 {
                return Some(list[0].clone());
            }
            let mid = list.len() / 2;
            let left = build(&list[..mid]);
            let right = build(&list[mid..]);
            match (left, right) {
                (Some(l), Some(r)) => Some(Box::new(RopeNode::internal((*l).clone(), (*r).clone()))),
                (Some(l), None) => Some(l),
                (None, Some(r)) => Some(r),
                (None, None) => None,
            }
        }
        build(&nodes)
    }

    /// Retrieves the full plain‑text representation of the document.
    pub fn to_string(&self) -> String {
        let mut result = String::new();
        self.traverse(&self.root, &mut result);
        result
    }

    fn traverse(&self, node: &Option<Box<RopeNode>>, out: &mut String) {
        if let Some(n) = node {
            if n.is_leaf() {
                let piece = n.piece.as_ref().unwrap();
                let buffer = if piece.buffer_id == 0 {
                    self.original_buffer.borrow()
                } else {
                    let idx = (piece.buffer_id - 1) as usize;
                    self.append_buffers.borrow()[idx].clone().into()
                };
                let slice = buffer
                    .chars()
                    .skip(piece.offset)
                    .take(piece.length)
                    .collect::<String>();
                out.push_str(&slice);
            } else {
                self.traverse(&n.left, out);
                self.traverse(&n.right, out);
            }
        }
    }
}

/// Errors that can be raised by the engine.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum EngineError {
    #[error("invalid edit range")]
    InvalidRange,
    #[error("corrupt internal state")]
    CorruptState,
}

impl From<EditError> for EngineError {
    fn from(e: EditError) -> Self {
        match e {
            EditError::InvalidRange => EngineError::InvalidRange,
        }
    }
}

// -----------------------------------------------------------------------------
// Unit tests for the core engine
// -----------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use crate::collab::crdt::{InsertPayload, DeletePayload};

    #[test]
    fn test_insert_at_beginning() {
        let mut engine = RopePieceTableEngine::new("world");
        engine.insert(0, "Hello ").unwrap();
        assert_eq!(engine.to_string(), "Hello world");
    }

    #[test]
    fn test_insert_at_end() {
        let mut engine = RopePieceTableEngine::new("Hello");
        engine.insert(5, " world").unwrap();
        assert_eq!(engine.to_string(), "Hello world");
    }

    #[test]
    fn test_insert_middle() {
        let mut engine = RopePieceTableEngine::new("Helo world");
        engine.insert(3, "l").unwrap();
        assert_eq!(engine.to_string(), "Hello world");
    }

    #[test]
    fn test_delete_range() {
        let mut engine = RopePieceTableEngine::new("Hello beautiful world");
        engine.delete(6..15).unwrap(); // remove "beautiful"
        assert_eq!(engine.to_string(), "Hello  world");
    }

    #[test]
    fn test_apply_insert_operation() {
        let mut engine = RopePieceTableEngine::new("");
        let op = DocumentOperation {
            op_id: Uuid::new_v4(),
            timestamp: 1,
            author: 0,
            kind: OperationKind::Insert,
            payload: InsertPayload {
                position: 0,
                text: "Hello".into(),
            }
            .into(),
        };
        engine.apply(op).unwrap();
        assert_eq!(engine.to_string(), "Hello");
    }

    #[test]
    fn test_apply_delete_operation() {
        let mut engine = RopePieceTableEngine::new("Hello world");
        let op = DocumentOperation {
            op_id: Uuid::new_v4(),
            timestamp: 2,
            author: 0,
            kind: OperationKind::Delete,
            payload: DeletePayload {
                range: 5..6, // delete space
            }
            .into(),
        };
        engine.apply(op).unwrap();
        assert_eq!(engine.to_string(), "Helloworld");
    }

    #[test]
    fn test_invalid_insert_position() {
        let mut engine = RopePieceTableEngine::new("test");
        let err = engine.insert(10, "fail").unwrap_err();
        assert_eq!(err, EditError::InvalidRange);
    }

    #[test]
    fn test_invalid_delete_range() {
        let mut engine = RopePieceTableEngine::new("test");
        let err = engine.delete(3..10).unwrap_err();
        assert_eq!(err, EditError::InvalidRange);
    }

    #[test]
    fn test_multiple_operations_sequence() {
        let mut engine = RopePieceTableEngine::new("");
        engine.insert(0, "world").unwrap();
        engine.insert(0, "Hello ").unwrap();
        engine.delete(5..6).unwrap(); // delete space after Hello
        assert_eq!(engine.to_string(), "HelloWorld");
    }
}