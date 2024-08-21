import fitz  # PyMuPDF
import re
from markdown import markdown
import os

def extract_highlighted_text_and_annotations(pdf_path):
    doc = fitz.open(pdf_path)
    highlights = {"blue": [], "yellow": [], "orange": []}
    text_annotations = []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        for annot in page.annots():
            if annot.type[0] == 8:  # Highlight annotation type
                color = annot.colors['stroke']  # Get the color of the highlight
                quad_points = annot.vertices
                text = ""
                for i in range(0, len(quad_points), 4):
                    # Extract text from the quad points (highlighted areas)
                    rect = fitz.Quad(quad_points[i:i+4]).rect
                    text += page.get_text("text", clip=rect)

                text = text.strip()
                if text:
                    color_name = classify_color(color)
                    if color_name:
                        highlights[color_name].append((text, page_num + 1))
            elif annot.type[0] == 0:  # Text annotation type
                annot_text = annot.info.get('content', '').strip()
                if annot_text:
                    text_annotations.append((annot_text, page_num + 1))

    return highlights, text_annotations

def classify_color(color):
    # Define color ranges
    blue = (0, 0, 1)
    yellow = (1, 1, 0)
    orange = (1, 0.65, 0)

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

def export_to_markdown(highlights, text_annotations, output_path):
    md_content = "# Highlighted Text and Annotations\n"
    
    # Highlights section
    for color, entries in highlights.items():
        md_content += f"\n## {color.capitalize()} Highlights\n"
        for text, page in entries:
            md_content += f"- **Page {page}**: {text}\n"
    
    # Text annotations section
    if text_annotations:
        md_content += "\n## Text Annotations\n"
        for text, page in text_annotations:
            md_content += f"- **Page {page}**: {text}\n"
    
    with open(output_path, "w") as md_file:
        md_file.write(markdown(md_content))

if __name__ == "__main__":
    # Set paths for input and output
    input_folder = os.path.join("annotation_extraction", "A")
    output_folder = os.path.join("annotation_extraction", "B")
    
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    pdf_file = "input.pdf"  # Replace with the actual file name
    pdf_path = os.path.join(input_folder, pdf_file)
    output_path = os.path.join(output_folder, "highlights_and_annotations.md")
    
    highlights, text_annotations = extract_highlighted_text_and_annotations(pdf_path)
    export_to_markdown(highlights, text_annotations, output_path)
    print(f"Exported highlighted text and annotations to {output_path}")
