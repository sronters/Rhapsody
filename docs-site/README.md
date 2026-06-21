# Rhapsody Docs Site

Mintlify documentation for Rhapsody.

```bash
cd docs-site
npm install
npm run check
npm run dev
```

The docs use `openapi.json`, exported from the FastAPI application:

```bash
python scripts/export_openapi.py
```

Supported documentation languages:

- `en` - English
- `ru` - Russian

Do not commit `node_modules/`. Install dependencies locally when working on the
docs site.
