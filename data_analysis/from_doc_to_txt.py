from docx import Document

def extract_text_from_docx(docx_path: str) -> str:
    doc = Document(docx_path)
    return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])

def save_text_to_file(docx_path: str, txt_path: str):
    text = extract_text_from_docx(docx_path)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

if __name__ == "__main__":
    save_text_to_file("data/instruction.docx", "data/instruction.txt")
    print("Инструкция сохранена в instruction.txt")
