import fitz  # PyMuPDF
import os
from spellchecker import SpellChecker

def clean_text(text):
    """Remove unwanted characters and clean up the text."""
    return text.encode('ascii', 'ignore').decode('ascii')

def spell_check_text(text):
    """Correct spelling in the text."""
    spell = SpellChecker()
    words = text.split()
    corrected_words = [spell.correction(word) if word not in spell else word for word in words]
    # Filter out None values
    corrected_words = [word if word is not None else '' for word in corrected_words]
    return ' '.join(corrected_words)

def extract_highlighted_text_and_annotations(pdf_path):
    doc = fitz.open(pdf_path)
    highlights = {
        "General Notes": [],
        "Definitions, Locations, People, Organizations": [],
        "Author Thesis and Methodology": [],
        "Important": [],
        "Stats": [],
        "Quotes": []
    }
    text_annotations = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        print(f"Processing page {page_num + 1}")

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

    return highlights, text_annotations

def classify_color(color):
    # Normalize color to range 0-1 if necessary
    if max(color) > 1:
        color = tuple(c / 255.0 for c in color)
    
    # Updated color mappings
    light_blue = (0.659, 0.929, 1.000)    # RGB for #A8EDFF
    yellow = (1.0, 1.0, 0.039)            # RGB for #FFFF0A
    orange = (0.992, 0.502, 0.031)        # RGB for #FD8008
    red = (1.0, 0.255, 0.494)             # RGB for #FF417E
    purple = (0.902, 0.522, 1.0)          # RGB for #E685FF
    gray = (0.902, 0.902, 0.902)          # RGB for #E6E6E6

    color_map = {
        "General Notes": light_blue,
        "Definitions, Locations, People, Organizations": yellow,
        "Author Thesis and Methodology": orange,
        "Important": red,
        "Stats": purple,
        "Quotes": gray
    }

    tolerance = 0.2  # Adjust this value if needed

    for color_name, ref_color in color_map.items():
        # Check if color matches reference color within tolerance
        if all(abs(c1 - c2) <= tolerance for c1, c2 in zip(color, ref_color)):
            return color_name
    return None

def export_to_markdown(highlights, text_annotations, output_path, original_filename, chronological_output_path):
    # Generate header for Git site compatibility
    md_content = f"# Highlights and Annotations from {original_filename}\n"
    md_content += "\nThis document contains the extracted highlights and annotations.\n"
    
    # Output sections in the specified order (Categorized output)
    for category in ["General Notes", "Definitions, Locations, People, Organizations", "Author Thesis and Methodology", "Stats", "Important", "Quotes"]:
        if category in highlights and highlights[category]:
            md_content += f"\n## {category}\n"
            for text, page in highlights[category]:
                md_content += f"- **Page {page}**: {text}\n"
    
    if text_annotations:
        md_content += f"\n## Text Annotations\n"
        for text, page in text_annotations:
            md_content += f"- **Page {page}**: {text}\n"
    
    # Write to categorized markdown file
    with open(output_path, "w") as md_file:
        md_file.write(md_content)
    
    # Generate chronological markdown content
    chronological_md_content = f"# Highlights and Annotations from {original_filename}\n"
    chronological_md_content += "\nThis document contains the extracted highlights and annotations arranged chronologically.\n"
    
    # Combine all texts by category and sort them by page
    categorized_texts = []
    for category in ["General Notes", "Definitions, Locations, People, Organizations", "Author Thesis and Methodology", "Stats", "Important", "Quotes"]:
        categorized_texts.extend((text, page, category) for text, page in highlights.get(category, []))
    categorized_texts.extend((text, page, "Text Annotations") for text, page in text_annotations)
    
    categorized_texts.sort(key=lambda x: x[1])

    for text, page, category in categorized_texts:
        # Output the category as a tag
        chronological_md_content += f"\n#{category}\n"
        chronological_md_content += f"- **Page {page}**: {text}\n"
    
    # Write to chronological markdown file
    with open(chronological_output_path, "w") as md_file:
        md_file.write(chronological_md_content)

if __name__ == "__main__":
    # Set paths for input and output
    input_folder = os.path.join("annotation_extraction", "A")
    output_folder = os.path.join("annotation_extraction", "B")
    
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Find the PDF file in the A folder
    pdf_files = [f for f in os.listdir(input_folder) if f.endswith(".pdf")]
    if len(pdf_files) != 1:
        raise ValueError("There should be exactly one PDF file in the 'A' folder.")
    
    original_filename = pdf_files[0].replace(".pdf", "")
    pdf_path = os.path.join(input_folder, pdf_files[0])
    
    categorized_output_filename = f"category_{original_filename}_highlights_and_annotations.md"
    chronological_output_filename = f"chronological_{original_filename}_highlights_and_annotations.md"
    
    categorized_output_path = os.path.join(output_folder, categorized_output_filename)
    chronological_output_path = os.path.join(output_folder, chronological_output_filename)
    
    highlights, text_annotations = extract_highlighted_text_and_annotations(pdf_path)
    export_to_markdown(highlights, text_annotations, categorized_output_path, original_filename, chronological_output_path)
    print(f"Exported categorized highlights and annotations to {categorized_output_path}")
    print(f"Exported chronological highlights and annotations to {chronological_output_path}")
