import os
import sys
from pathlib import Path
from unittest import mock

# the llm is always mocked in the tests: no cost, no internet, no real key
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

# make the python/ modules importable (quran_detect, modify_paragraph, ...)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))


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
