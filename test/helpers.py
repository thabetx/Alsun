import os
import sys
from pathlib import Path
from unittest import mock

# the llm is always mocked in the tests: no cost, no internet, no real key
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

# make the python/ modules importable (quran_detect, modify_paragraph, ...)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

# The tests must not depend on the real .env of whoever runs them: llm.py reads the keys from it, so it is pointed
# to a file that does not exist, and the key of Cohere is empty (a test that needs one sets a fake key itself).
import llm  # noqa: E402

llm.ENV_FILE = Path(__file__).resolve().parent / "no-such-file.env"
os.environ["COHERE_API_KEY"] = ""

# The trusted Islamic terms (data/terminology) would add a part to every prompt that has one of their words, so the
# tests do not read the real files: a test of the terms points TERMINOLOGY_DIR to its own folder.
import trusted_terms  # noqa: E402

trusted_terms.TERMINOLOGY_DIR = Path(__file__).resolve().parent / "no-such-folder"


class FakeLlm:
    # stands in for client.chat.completions.create and remembers what was sent
    def __init__(self, reply_function):
        self.reply_function = reply_function
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        response = mock.Mock()
        response.choices = [mock.Mock()]
        response.choices[0].message.content = self.reply_function(kwargs)
        return response


def echo_last_line(kwargs):
    # reply = the text after the last "...: " of the user message, wrapped as <LLM:...>
    user_message = kwargs["messages"][1]["content"]
    return "<LLM:" + user_message.split(": ")[-1] + ">"
