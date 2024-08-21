import fitz  # PyMuPDF
import os
from spellchecker import SpellChecker
import isbnlib  # For extracting citation metadata

def clean_text(text):
    """Remove unwanted characters and clean up the text."""
    cleaned_text = text.encode('ascii', 'ignore').decode('ascii')
    return cleaned_text

def spell_check_text(text):
    """Correct spelling in the text."""
    spell = SpellChecker()
    words = text.split()
    corrected_words = [spell.correction(word) if word not in spell else word for word in words]
    corrected_words = [word if word is not None else '' for word in corrected_words]
    return ' '.join(corrected_words)

def extract_highlighted_text_and_annotations(pdf_path):
    doc = fitz.open(pdf_path)
    highlights = {"General Notes": [], "Definitions, Locations, People": [], "Author Thesis and Methodology": [], "Important": [], "Stats": []}
    text_annotations = []
    chapters = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        ocr_text = page.get_text("text")
        chapters += extract_chapter_titles(ocr_text, page_num + 1)

        for annot in page.annots() or []:
            annot_type = annot.type[0]
            color = annot.colors.get('stroke', (0, 0, 0))
            quad_points = annot.vertices if annot_type == 8 else None
            text = ""

            if annot_type == 8:  # Highlight annotation type
                if quad_points:
                    for i in range(0, len(quad_points), 4):
                        rect = fitz.Quad(quad_points[i:i+4]).rect
                        text += page.get_text("text", clip=rect)
                    text = clean_text(text.strip())
                    text = spell_check_text(text)
                    if text:
                        color_name = classify_color(color)
                        if color_name:
                            highlights[color_name].append((text, page_num + 1))
            elif annot_type == 1:  # Comment annotation type
                annot_info = annot.info
                annot_text = annot_info.get('content', '')
                if not annot_text:
                    annot_text = annot_info.get('title', '')
                annot_text = clean_text(annot_text.strip())
                annot_text = spell_check_text(annot_text)
                if annot_text:
                    text_annotations.append((annot_text, page_num + 1))

    return highlights, text_annotations, chapters

def classify_color(color):
    color_map = {
        "General Notes": (0.659, 0.929, 1.000),  # RGB for #A8EDFF
        "Definitions, Locations, People": (1.0, 1.0, 0.0),  # RGB for #FFFF00 (close to yellow)
        "Author Thesis and Methodology": (0.996, 0.800, 0.400),  # RGB for #FECC66
        "Important": (1.0, 0.369, 0.565),  # RGB for #FF5E90
        "Stats": (0.843, 0.984, 0.0)  # RGB for #D7FB00
    }

    tolerance = 0.2

    def within_tolerance(c1, c2):
        return all(abs(c1 - c2) < tolerance for c1, c2 in zip(c1, c2))

    for color_name, ref_color in color_map.items():
        if within_tolerance(color, ref_color):
            return color_name
    return None

def extract_chapter_titles(ocr_text, page_num):
    lines = ocr_text.splitlines()
    chapters = []
    for line in lines:
        if line.strip().lower().startswith("chapter"):
            chapters.append((line.strip(), page_num))
    return chapters

def get_book_metadata(pdf_path):
    metadata = fitz.open(pdf_path).metadata
    title = metadata.get('title', 'Unknown Title')
    author = metadata.get('author', 'Unknown Author')
    # Assuming the title contains the author's last name and book title
    return author, title

def export_to_markdown(highlights, text_annotations, chapters, output_path, original_filename, chronological_output_path):
    author, title = get_book_metadata(pdf_path)

    md_content = f"# Highlights and Annotations from {author} - {title}\n"
    md_content += f"\n{author}. *{title}*. Publisher, Year.\n"
    
    for chapter, page_num in chapters:
        md_content += f"\n## {chapter} (Page {page_num})\n"
        for category in ["General Notes", "Definitions, Locations, People", "Author Thesis and Methodology", "Stats", "Important"]:
            if category in highlights:
                if highlights[category]:
                    md_content += f"\n### {category}\n"
                    for text, page in highlights[category]:
                        if page == page_num:
                            md_content += f"- **Page {page}**: {text}\n"
    
    if text_annotations:
        md_content += f"\n### Text Annotations\n"
        for text, page in text_annotations:
            md_content += f"- **Page {page}**: {text}\n"
    
    with open(output_path, "w") as md_file:
        md_file.write(md_content)
    
    chronological_md_content = f"# Highlights and Annotations from {author} - {title}\n"
    chronological_md_content += f"\n{author}. *{title}*. Publisher, Year.\n"
    
    categorized_texts = []
    for category in ["General Notes", "Definitions, Locations, People", "Author Thesis and Methodology", "Stats", "Important"]:
        categorized_texts.extend((text, page, category) for text, page in highlights.get(category, []))
    categorized_texts.extend((text, page, "Text Annotations") for text, page in text_annotations)
    categorized_texts.sort(key=lambda x: x[1])

    for chapter, page_num in chapters:
        chronological_md_content += f"\n## {chapter} (Page {page_num})\n"
        for text, page, category in categorized_texts:
            if page == page_num:
                chronological_md_content += f"\n### {category}\n"
                chronological_md_content += f"- **Page {page}**: {text}\n"
    
    with open(chronological_output_path, "w") as md_file:
        md_file.write(chronological_md_content)

if __name__ == "__main__":
    input_folder = os.path.join("annotation_extraction", "A")
    output_folder = os.path.join("annotation_extraction", "B")
    
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    pdf_files = [f for f in os.listdir(input_folder) if f.endswith(".pdf")]
    if len(pdf_files) != 1:
        raise ValueError("There should be exactly one PDF file in the 'A' folder.")
    
    original_filename = pdf_files[0].replace(".pdf", "")
    pdf_path = os.path.join(input_folder, pdf_files[0])
    
    categorized_output_filename = f"{original_filename}_highlights_and_annotations.md"
    chronological_output_filename = f"{original_filename}_chronological_highlights_and_annotations.md"
    
    categorized_output_path = os.path.join(output_folder, categorized_output_filename)
    chronological_output_path = os.path.join(output_folder, chronological_output_filename)
    
    highlights, text_annotations, chapters = extract_highlighted_text_and_annotations(pdf_path)
    export_to_markdown(highlights, text_annotations, chapters, categorized_output_path, original_filename, chronological_output_path)
    print(f"Exported categorized highlights and annotations to {categorized_output_path}")
    print(f"Exported chronological highlights and annotations to {chronological_output_path}")
