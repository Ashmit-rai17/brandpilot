"""SPIKE C: ASI1 chat returns parseable JSON. python spikes/spike_c_llm.py"""
from dotenv import load_dotenv

load_dotenv()
from brandpilot.brain import Brain  # noqa: E402
from brandpilot.models import Brief  # noqa: E402

b = Brain()
brief = b.extract_brief("We're Forge, an AI productivity tool for senior developers. Calm, precise, premium. "
                        "Headline: Ship calmer, build faster", Brief())
print("source:", b.last_source, "\n", brief.model_dump_json(indent=1))
print(b.choose_directions(brief), "\nsource:", b.last_source)
