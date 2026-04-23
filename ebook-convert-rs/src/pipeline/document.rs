//! OEB Document — the intermediate representation.
//!
//! This is the in-memory "unpacked EPUB" that all formats convert to/from.
//! Equivalent to Calibre's OEBBook class.

use std::collections::HashMap;
use std::sync::LazyLock;

use regex::Regex;

use super::metadata::Metadata;

static RE_STRIP_TAGS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]+>").unwrap());

/// A complete book in intermediate representation.
#[derive(Debug, Clone)]
pub struct OebDocument {
    /// Book metadata (title, authors, ISBN, etc.)
    pub metadata: Metadata,

    /// Spine: ordered list of content file names (reading order)
    pub spine: Vec<String>,

    /// Content files: name → XHTML content
    pub html_files: HashMap<String, String>,

    /// Stylesheets: name → CSS content
    pub stylesheets: HashMap<String, String>,

    /// Images: name → raw bytes
    pub images: HashMap<String, Vec<u8>>,

    /// Fonts: name → raw bytes
    pub fonts: HashMap<String, Vec<u8>>,

    /// Table of contents
    pub toc: Vec<TocEntry>,

    /// Guide references (cover, toc, etc.)
    pub guide: Vec<GuideRef>,

    /// MIME type map: filename → media type
    pub mime_map: HashMap<String, String>,
}

/// A table of contents entry (recursive tree).
#[derive(Debug, Clone)]
pub struct TocEntry {
    pub title: String,
    pub href: String,
    pub children: Vec<TocEntry>,
}

/// A guide reference (cover page, TOC page, etc.)
#[derive(Debug, Clone)]
pub struct GuideRef {
    pub ref_type: String, // "cover", "toc", "text", etc.
    pub title: String,
    pub href: String,
}

impl OebDocument {
    pub fn new() -> Self {
        Self {
            metadata: Metadata::default(),
            spine: Vec::new(),
            html_files: HashMap::new(),
            stylesheets: HashMap::new(),
            images: HashMap::new(),
            fonts: HashMap::new(),
            toc: Vec::new(),
            guide: Vec::new(),
            mime_map: HashMap::new(),
        }
    }

    /// Add an HTML content file to the document.
    pub fn add_html(&mut self, name: impl Into<String>, content: impl Into<String>) {
        let name = name.into();
        self.mime_map
            .insert(name.clone(), "application/xhtml+xml".into());
        self.html_files.insert(name.clone(), content.into());
        if !self.spine.contains(&name) {
            self.spine.push(name);
        }
    }

    /// Add a stylesheet.
    pub fn add_css(&mut self, name: impl Into<String>, content: impl Into<String>) {
        let name = name.into();
        self.mime_map.insert(name.clone(), "text/css".into());
        self.stylesheets.insert(name, content.into());
    }

    /// Add an image.
    pub fn add_image(&mut self, name: impl Into<String>, data: Vec<u8>, mime: &str) {
        let name = name.into();
        self.mime_map.insert(name.clone(), mime.into());
        self.images.insert(name, data);
    }

    /// Get all resource names in manifest order.
    pub fn manifest_items(&self) -> Vec<(&str, &str)> {
        self.mime_map
            .iter()
            .map(|(name, mime)| (name.as_str(), mime.as_str()))
            .collect()
    }

    /// Extract plain text from all HTML files (for search, fingerprinting, etc.)
    pub fn plain_text(&self) -> String {
        // Simple tag stripping — a real implementation would use html5ever
        let mut text = String::new();
        for name in &self.spine {
            if let Some(html) = self.html_files.get(name) {
                let stripped = RE_STRIP_TAGS.replace_all(html, " ");
                text.push_str(&stripped);
                text.push('\n');
            }
        }
        text
    }
}

impl Default for OebDocument {
    fn default() -> Self {
        Self::new()
    }
}
