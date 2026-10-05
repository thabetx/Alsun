from dotenv import load_dotenv
from openai import OpenAI
from llm import chat_text
from paragraph_format import concatenate_paragraph_segements, build_paragraph_display_parts

# reads OPENAI_API_KEY from a .env file (or the environment)
load_dotenv()
client = OpenAI()


def modify_normal_paragraph(paragraph, instructions, model=None):
    system_prompt = (
        "You edit a translated text. Apply the user's instructions to the text. "
        "Reply with only the modified text, no explanations or extra text."
    )
    return chat_text(client, [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Instructions: {instructions}\n\nText: {paragraph}"},
    ], model)


def modify_paragraph(paragraph, instructions, model=None):
    # paragraph = list of dictionaries like split_quran_and_normal_paragraph returns
    modified_paragraph = []
    for segment in paragraph:
        if segment["type"] == "normal":
            # only the normal text goes to the llm, in the same structure
            modified_paragraph.append({**segment, "text": modify_normal_paragraph(segment["text"], instructions, model)})
        else:
            # quran stays exactly as it is
            modified_paragraph.append(segment)

    return modified_paragraph


def modify_paragraph_and_build_response(segments, instructions, model=None):
    modified_segments = modify_paragraph(segments, instructions, model)
    return {
        "paragraph": concatenate_paragraph_segements(modified_segments),
        "parts": build_paragraph_display_parts(modified_segments),
        "segments": modified_segments,
    }
