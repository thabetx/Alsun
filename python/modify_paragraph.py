from dotenv import load_dotenv
from openai import OpenAI
from paragraph_format import concatenate_paragraph_segements, build_paragraph_display_parts

# reads OPENAI_API_KEY from a .env file (or the environment)
load_dotenv()
client = OpenAI()


def modify_normal_paragraph(paragraph, instructions):
    system_prompt = (
        "You edit a translated text. Apply the user's instructions to the text. "
        "Reply with only the modified text, no explanations or extra text."
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Instructions: {instructions}\n\nText: {paragraph}"},
        ],
    )
    return response.choices[0].message.content


def modify_paragraph(paragraph, instructions):
    # paragraph = list of dictionaries like split_quran_and_normal_paragraph returns
    modified_paragraph = []
    for segment in paragraph:
        if segment["type"] == "normal":
            # only the normal text goes to the llm, in the same structure
            modified_paragraph.append({**segment, "text": modify_normal_paragraph(segment["text"], instructions)})
        else:
            # quran stays exactly as it is
            modified_paragraph.append(segment)

    return modified_paragraph


def modify_paragraph_and_build_response(segments, instructions):
    modified_segments = modify_paragraph(segments, instructions)
    return {
        "paragraph": concatenate_paragraph_segements(modified_segments),
        "parts": build_paragraph_display_parts(modified_segments),
        "segments": modified_segments,
    }
