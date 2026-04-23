//! Book metadata — Dublin Core + extensions.

use serde::{Deserialize, Serialize};

/// Complete book metadata, matching Dublin Core + Calibre extensions.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Metadata {
    pub title: String,
    pub title_sort: Option<String>,
    pub authors: Vec<String>,
    pub author_sort: Option<String>,
    pub publisher: Option<String>,
    pub description: Option<String>,
    pub isbn: Option<String>,
    pub language: Option<String>,
    pub languages: Vec<String>,
    pub tags: Vec<String>,
    pub series: Option<String>,
    pub series_index: Option<f64>,
    pub rating: Option<f64>,
    pub pubdate: Option<String>,
    pub identifiers: std::collections::HashMap<String, String>,
    pub uuid: Option<String>,
    pub cover_image: Option<String>, // filename in images map
    pub rights: Option<String>,
}

impl Metadata {
    pub fn new(title: impl Into<String>) -> Self {
        Self {
            title: title.into(),
            ..Default::default()
        }
    }

    /// Get the primary language, defaulting to "en".
    pub fn primary_language(&self) -> &str {
        self.language
            .as_deref()
            .or(self.languages.first().map(|s| s.as_str()))
            .unwrap_or("en")
    }
}
