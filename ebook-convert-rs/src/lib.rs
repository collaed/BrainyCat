//! ebook-convert: Open-source ebook format converter in Rust.
//!
//! Architecture mirrors Calibre's proven pipeline:
//!   Input Plugin → OEB Document (intermediate) → Transforms → Output Plugin
//!
//! The OEB Document is an in-memory representation of a book as structured
//! XHTML + CSS + images + metadata, similar to an unpacked EPUB.

pub mod formats;
pub mod pipeline;
pub mod transforms;

pub use pipeline::convert;
pub use pipeline::document::OebDocument;
pub use pipeline::is_lenient;
pub use pipeline::metadata::Metadata;
