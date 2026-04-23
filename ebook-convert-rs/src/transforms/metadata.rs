//! Metadata transform — ensure metadata is complete and consistent.

use anyhow::Result;

use crate::pipeline::document::OebDocument;

/// Update and normalize metadata.
pub fn update(doc: &mut OebDocument) -> Result<()> {
    // Generate UUID if missing
    if doc.metadata.uuid.is_none() {
        doc.metadata.uuid = Some(format!("urn:uuid:{}", simple_uuid()));
    }

    // Generate title_sort if missing
    if doc.metadata.title_sort.is_none() {
        doc.metadata.title_sort = Some(title_sort(&doc.metadata.title));
    }

    // Generate author_sort if missing
    if doc.metadata.author_sort.is_none() && !doc.metadata.authors.is_empty() {
        doc.metadata.author_sort = Some(author_sort(&doc.metadata.authors[0]));
    }

    // Ensure at least one language
    if doc.metadata.languages.is_empty() {
        doc.metadata.languages.push("en".into());
        doc.metadata.language = Some("en".into());
    }

    Ok(())
}

/// Generate title sort: strip leading articles.
/// "The Great Gatsby" → "Great Gatsby, The"
fn title_sort(title: &str) -> String {
    let articles = ["the ", "a ", "an ", "le ", "la ", "les ", "l'", "un ", "une ", "des ",
                     "der ", "die ", "das ", "ein ", "eine ", "el ", "los ", "las "];
    let lower = title.to_lowercase();
    for article in &articles {
        if lower.starts_with(article) {
            let rest = &title[article.len()..];
            let art = &title[..article.trim_end().len()];
            return format!("{rest}, {art}");
        }
    }
    title.to_string()
}

/// Generate author sort: "First Last" → "Last, First"
fn author_sort(author: &str) -> String {
    if author.contains(',') {
        return author.to_string(); // Already in "Last, First" format
    }
    let parts: Vec<&str> = author.rsplitn(2, ' ').collect();
    if parts.len() == 2 {
        format!("{}, {}", parts[0], parts[1])
    } else {
        author.to_string()
    }
}

/// Simple UUID v4 generation without external dependency.
fn simple_uuid() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let t = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    let seed = t.as_nanos();
    format!(
        "{:08x}-{:04x}-4{:03x}-{:04x}-{:012x}",
        (seed & 0xFFFFFFFF) as u32,
        ((seed >> 32) & 0xFFFF) as u16,
        ((seed >> 48) & 0x0FFF) as u16,
        (((seed >> 60) & 0x3FFF) | 0x8000) as u16,
        (seed >> 74) & 0xFFFFFFFFFFFF,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_title_sort() {
        assert_eq!(title_sort("The Great Gatsby"), "Great Gatsby, The");
        assert_eq!(title_sort("A Tale of Two Cities"), "Tale of Two Cities, A");
        assert_eq!(title_sort("Les Misérables"), "Misérables, Les");
        assert_eq!(title_sort("Dune"), "Dune");
    }

    #[test]
    fn test_author_sort() {
        assert_eq!(author_sort("Frank Herbert"), "Herbert, Frank");
        assert_eq!(author_sort("Herbert, Frank"), "Herbert, Frank");
        assert_eq!(author_sort("J.R.R. Tolkien"), "Tolkien, J.R.R.");
    }
}
