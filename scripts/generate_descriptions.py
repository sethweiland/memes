"""Generate template descriptions for 100 more meme templates."""
import os
import json
from dotenv import load_dotenv

load_dotenv()

from src.core.templates import TemplatesCatalog, TEMPLATE_DESCRIPTIONS
from src.core.grok import GrokClient

catalog = TemplatesCatalog()
grok = GrokClient()

# Get templates without descriptions
existing = set(TEMPLATE_DESCRIPTIONS.keys())
missing = [t for t in catalog.templates.values() if t.name not in existing]
print(f'Templates without descriptions: {len(missing)}')

new_descriptions = {}
skipped = 0

# Process in batches of 10
batch_size = 10
for i in range(0, min(150, len(missing)), batch_size):
    batch = missing[i:i+batch_size]

    template_list = '\n'.join([f'- {t.name} ({t.box_count} text boxes)' for t in batch])

    prompt = f'''For each meme template, provide a BRIEF description of what goes in each text box.
If you don't recognize a template or aren't sure, say SKIP.

Templates:
{template_list}

Respond with this exact format for each:

TEMPLATE: exact name
DESCRIPTION: TOP_TEXT=what goes here, BOTTOM_TEXT=what goes here. Brief usage.

or if unknown:

TEMPLATE: exact name
SKIP

Go through each:'''

    try:
        response = grok._chat([{'role': 'user', 'content': prompt}], max_tokens=2000, temperature=0.3)

        current_template = None
        for line in response.split('\n'):
            line = line.strip()
            if line.startswith('TEMPLATE:'):
                current_template = line.replace('TEMPLATE:', '').strip()
            elif line == 'SKIP' and current_template:
                skipped += 1
                current_template = None
            elif line.startswith('DESCRIPTION:') and current_template:
                desc = line.replace('DESCRIPTION:', '').strip()
                if desc and len(desc) > 20:
                    new_descriptions[current_template] = desc
                current_template = None

        print(f'Batch {i//batch_size + 1}: {len(new_descriptions)} added, {skipped} skipped')

        if len(new_descriptions) >= 100:
            break

    except Exception as e:
        print(f'Batch error: {e}')

print(f'\nTotal: {len(new_descriptions)} new descriptions')
print(f'Skipped: {skipped}')

# Save
with open('data/new_template_descriptions.json', 'w') as f:
    json.dump(new_descriptions, f, indent=2)

print('Saved to data/new_template_descriptions.json')

# Show samples
print('\nSamples:')
for name, desc in list(new_descriptions.items())[:5]:
    print(f'  {name}: {desc[:70]}...')
