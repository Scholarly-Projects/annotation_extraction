import fitz  # PyMuPDF
import os
from spellchecker import SpellChecker

def clean_text(text):
    """Remove unwanted characters and clean up the text."""
    cleaned_text = text.encode('ascii', 'ignore').decode('ascii')
    return cleaned_text

def spell_check_text(text):
    """Correct spelling in the text."""
    spell = SpellChecker()
    words = text.split()
    corrected_words = [spell.correction(word) if word not in spell else word for word in words]
    
    # Filter out any None values and join the corrected words
    corrected_words = [word if word is not None else '' for word in corrected_words]
    
    return ' '.join(corrected_words)

def extract_highlighted_text_and_annotations(pdf_path):
    doc = fitz.open(pdf_path)
    highlights = {"blue": [], "yellow": [], "orange": []}
    text_annotations = []
    rectangle_texts = []

    all_texts = []  # To store text for chronological order

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        print(f"Processing page {page_num + 1}")

        for annot in page.annots() or []:
            print(f"Annotation: {annot}")
            annot_type = annot.type[0]
            print(f"Annotation Type: {annot_type}")
            color = annot.colors.get('stroke', (0, 0, 0))
            print(f"Color: {color}")
            quad_points = annot.vertices if annot_type == 8 else None
            text = ""

            if annot_type == 8:  # Highlight annotation type
                if quad_points:
                    for i in range(0, len(quad_points), 4):
                        rect = fitz.Quad(quad_points[i:i+4]).rect
                        text += page.get_text("text", clip=rect)
                    text = clean_text(text.strip())
                    if text:
                        color_name = classify_color(color)
                        if color_name:
                            highlighted_text = spell_check_text(text)  # Correct spelling in text
                            highlights[color_name].append((highlighted_text, page_num + 1))
                            all_texts.append((color_name, highlighted_text, page_num + 1))
            elif annot_type == 1:  # Text annotation type
                annot_info = annot.info
                print(f"Annotation Info: {annot_info}")
                annot_text = annot_info.get('content', '')
                if not annot_text:
                    annot_text = annot_info.get('title', '')
                annot_text = clean_text(annot_text.strip())
                if annot_text:
                    annot_text = spell_check_text(annot_text)  # Correct spelling in text
                    text_annotations.append((annot_text, page_num + 1))
                    all_texts.append(('Text Annotations', annot_text, page_num + 1))
            elif annot_type == 2:  # Rectangle annotation type
                rect = fitz.Rect(annot.rect)
                text_in_rect = extract_text_in_rectangle(page, rect)
                if text_in_rect:
                    rectangle_texts.append((clean_text(text_in_rect), page_num + 1))
                    all_texts.append(('Important', text_in_rect, page_num + 1))

    return highlights, text_annotations, rectangle_texts, all_texts

def classify_color(color):
    # Define color ranges
    blue = (0.659, 0.929, 1.000)  # RGB for #A8EDFF
    yellow = (1.0, 1.0, 0.0)      # RGB for #FFFF00 (close to yellow)
    orange = (0.996, 0.800, 0.400) # RGB for #FECC66

    color_map = {
        "blue": blue,
        "yellow": yellow,
        "orange": orange
    }

    # Match the color to the closest one
    for color_name, ref_color in color_map.items():
        if all(abs(c1 - c2) < 0.1 for c1, c2 in zip(color, ref_color)):
            return color_name
    return None

def extract_text_in_rectangle(page, rect):
    text = ""
    blocks = page.get_text("blocks")
    for block in blocks:
        block_rect = fitz.Rect(block[:4])
        if rect.intersects(block_rect):
            # Check if the text block is within the vertical range of the rectangle
            if block_rect.y0 >= rect.y0 and block_rect.y1 <= rect.y1:
                text += block[4].strip() + "\n"
    return clean_text(text.strip())

def export_to_markdown(highlights, text_annotations, rectangle_texts, output_path, original_filename):
    # Generate header for Git site compatibility
    md_content = f"# Highlights and Annotations from {original_filename}\n"
    md_content += "\nThis document contains the extracted highlights and annotations.\n"
    
    # Highlights section by color
    for color in ["blue", "yellow", "orange"]:
        if highlights[color]:
            section_title = {
                "blue": "General Notes",
                "yellow": "Definitions, Locations, People and Stats",
                "orange": "Author Thesis and Methodology"
            }[color]
            md_content += f"\n## {section_title}\n"
            for text, page in highlights[color]:
                md_content += f"- **Page {page}**: {text}\n"
    
    # Rectangle annotations section
    if rectangle_texts:
        md_content += "\n## Important\n"
        for text, page in rectangle_texts:
            md_content += f"- **Page {page}**: {text}\n"
    
    # Text annotations section
    if text_annotations:
        md_content += "\n## Text Annotations\n"
        for text, page in text_annotations:
            md_content += f"- **Page {page}**: {text}\n"
    
    # Write to markdown file
    with open(output_path, "w") as md_file:
        md_file.write(md_content)

def export_to_markdown_chronological(all_texts, output_path, original_filename):
    # Generate header for Git site compatibility
    md_content = f"# Highlights and Annotations from {original_filename}\n"
    md_content += "\nThis document contains the extracted highlights and annotations in chronological order.\n"
    
    # Chronological order
    for section_type, text, page in sorted(all_texts, key=lambda x: (x[2], x[0])):
        if section_type == 'blue':
            section_title = "General Notes"
        elif section_type == 'yellow':
            section_title = "Definitions, Locations, People and Stats"
        elif section_type == 'orange':
            section_title = "Author Thesis and Methodology"
        elif section_type == 'Text Annotations':
            section_title = "Text Annotations"
        elif section_type == 'Important':
            section_title = "Important"
        else:
            continue
        
        md_content += f"\n## {section_title}\n"
        md_content += f"- **Page {page}**: {text}\n"
    
    # Write to markdown file
    with open(output_path, "w") as md_file:
        md_file.write(md_content)

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
    output_filename = f"{original_filename}_highlights_and_annotations.md"
    output_path = os.path.join(output_folder, output_filename)
    
    # Extract text and annotations
    highlights, text_annotations, rectangle_texts, all_texts = extract_highlighted_text_and_annotations(pdf_path)
    
    # Export categorized order
    export_to_markdown(highlights, text_annotations, rectangle_texts, output_path, original_filename)
    print(f"Exported categorized highlights and annotations to {output_path}")
    
    # Export chronological order
    chronological_output_filename = f"{original_filename}_chronological_highlights_and_annotations.md"
    chronological_output_path = os.path.join(output_folder, chronological_output_filename)
    export_to_markdown_chronological(all_texts, chronological_output_path, original_filename)
    print(f"Exported chronological highlights and annotations to {chronological_output_path}")
