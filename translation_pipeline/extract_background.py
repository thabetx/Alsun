import fitz  # pymupdf


def remove_text_from_pdf_page(pdf_page):
    # mark every text block for removal, with no fill so the background under it is untouched
    for text_block in pdf_page.get_text("blocks"):
        if text_block[6] == 0:  # 0 = text block, 1 = image block
            pdf_page.add_redact_annot(fitz.Rect(text_block[:4]), fill=False)

    # remove the text only, keep images and drawings (lines, borders, shapes)
    pdf_page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
        text=fitz.PDF_REDACT_TEXT_REMOVE,
    )


def extract_background_image(pdf_path, output_image_path, page_number=0, zoom=3):
    pdf_document = fitz.open(pdf_path)
    pdf_page = pdf_document[page_number]

    remove_text_from_pdf_page(pdf_page)

    # render the page as an image, zoom = quality (3 = 3x the pdf size)
    pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    pixmap.save(output_image_path)
    return output_image_path


if __name__ == "__main__":
    extract_background_image(r"C:\Users\abum\Downloads\page.pdf", "page_background.png")
    print("saved page_background.png")
