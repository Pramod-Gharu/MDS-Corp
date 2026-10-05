---
name: gbp-blog-post
description: Publishes a live WordPress blog URL to the MDS Industrial Google Business Profile. Use when the user pastes an mdsindustrialcorp.com article link, asks to post a blog to GBP, or runs /gbp-post.
---

# GBP blog post

When the user gives a page/blog URL, publish it to Google Business Profile. Do not ask them to run the command themselves unless it fails.

## Run

```bash
python3 scripts/gbp_connect.py from-blog "BLOG_URL"
```

Use the exact URL they pasted. Requires network.

## Required format (do not change)

- Description = WordPress title
- Image = featured image (the script converts WebP to JPEG if needed)
- Button = Learn more
- Link = article URL with `utm_source=GBP_post` and `utm_medium=page_share`

Post to the pinned listing **MDS Industrial Racking Inc.**

## Rules

- The article must already be published and have a featured image.
- Never read, print, or commit `.mds/wp.json` or `.mds/gbp-oauth.json`.
- Do not ask for passwords or tokens.
- If `status` is not `auth ok`, run `python3 scripts/gbp_connect.py status` and report only the status lines.

## Reply

Report only:

```text
post    ok
location        ...
description     ...
button  LEARN_MORE
link    ...?utm_source=GBP_post&utm_medium=page_share
```

If it fails, show the error line and the next fix. Do not invent a post.
