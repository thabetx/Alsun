import json
from datalab_sdk import DatalabClient, ConvertOptions

client = DatalabClient(api_key="hOqLUjJtLx8Os_ZPtG1toGsRBoOVgiBbjwCeJqk8X00")

options = ConvertOptions(
    output_format="json",
    mode="accurate",
    paginate=True,
    page_range="0-1",
)

result = client.convert("../data/two-pages.pdf", options=options)
with open("../data/page.json", "w", encoding="utf-8") as f:
    json.dump(result.json, f, indent=2)
print(result.cost_breakdown)