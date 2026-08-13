"""Custom parsers for companies that run their own careers portal.

This is the extension point for the "on-website postings" feature.
The rest of the pipeline does not care where a job came from, so a custom
parser only has to return the same normalized shape:

    [{"id", "title", "location", "url", "description"}, ...]

To add one:
  1. Create parsers/custom/<name>.py with a fetch(cfg, ua) function.
  2. Import it below and add it to CUSTOM.
  3. In companies.yaml:
         - name: Tesla
           ats: custom
           handler: tesla
           tier: california

See _example.py for a template.
"""

CUSTOM = {}

# Uncomment as you write them:
# from . import tesla
# CUSTOM["tesla"] = tesla.fetch
