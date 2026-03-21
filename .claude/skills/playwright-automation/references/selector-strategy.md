# Selector Robustness Strategy

This document explains the full selector ranking, why each level exists, and
how to make the right choice in ambiguous situations.

---

## The Robustness Ladder

Selectors are ranked by how likely they are to survive routine UI changes
(redesigns, copy edits, framework upgrades, responsive layout shifts). The
higher the rank, the more intentionally stable the attribute is.

### Tier 1 — Purpose-Built for Testing (Best)

#### 1.1 Test IDs: `data-testid`, `data-test`, `data-cy`

```python
page.get_by_test_id("submit-order")
```

**Why top tier:** These attributes exist solely for automation/testing. Devs
add them intentionally and they're excluded from styling, so they survive CSS
refactors and copy changes. They're the only selectors with an implicit
contract: "this won't change without a deliberate decision."

**Detection:**
```bash
playwright-cli eval "document.querySelectorAll('[data-testid]').length"
playwright-cli eval "JSON.stringify(Array.from(document.querySelectorAll('[data-testid]')).map(el => ({testId: el.dataset.testid, tag: el.tagName})))"
```

**Gotcha:** Some apps use `data-test`, `data-cy`, `data-qa`, or
`data-automation-id`. Check for all variants:
```bash
playwright-cli eval "(() => { const prefixes = ['data-testid','data-test','data-cy','data-qa','data-automation-id']; const results = {}; prefixes.forEach(p => { results[p] = document.querySelectorAll('['+p+']').length; }); return JSON.stringify(results); })()"
```

---

### Tier 2 — Semantic & Accessible

#### 2.1 ARIA Role + Accessible Name

```python
page.get_by_role("button", name="Place Order")
page.get_by_role("heading", name="Shopping Cart")
page.get_by_role("link", name="View Details")
page.get_by_role("textbox", name="Search")
```

**Why strong:** Roles are semantic and enforced by accessibility standards.
The accessible name comes from the element's text, `aria-label`, or
associated `<label>`. These change less often than CSS classes because
changing them affects screen reader users — product teams are cautious about
that.

**When to use:** Ideal for buttons, links, headings, and form controls that
have clear visible text or labels.

**Gotcha:** If two buttons have the same text (e.g., multiple "Delete"
buttons in a list), role+name isn't unique. In that case, scope it:
```python
page.locator('[data-testid="order-123"]').get_by_role("button", name="Delete")
```

#### 2.2 Label Association

```python
page.get_by_label("Email address")
page.get_by_label("Password")
```

**Why strong:** `<label>` elements are a formal accessibility requirement.
They rarely change because they're user-facing copy tied to form design.

**Best for:** Form inputs with proper `<label for="...">` associations.

**Detection:**
```bash
playwright-cli eval "(() => { const inputs = document.querySelectorAll('input, select, textarea'); return JSON.stringify(Array.from(inputs).map(el => ({ id: el.id, name: el.name, label: el.labels?.[0]?.textContent?.trim() || null, ariaLabel: el.getAttribute('aria-label') || null }))); })()"
```

#### 2.3 Placeholder Text

```python
page.get_by_placeholder("Enter your email")
```

**Why decent:** Placeholders are user-facing copy, less formal than labels
but still intentional. They change during copy updates but not during CSS
refactors.

**When to use:** Only when there's no `<label>` or `aria-label` — and the
placeholder is specific enough to be unique.

---

### Tier 3 — Structural & Attribute-Based

#### 3.1 Unique HTML `id`

```python
page.locator("#login-form")
page.locator("#main-search")
```

**Why mid-tier (not higher):** IDs should be unique per spec, but in practice
they're often auto-generated (`id="react-select-3-input"`,
`id="__next-build-watcher"`) or duplicated across components. A stable,
human-written ID is great. A framework-generated one is worthless.

**Rule:** Use IDs only if they look intentional (short, descriptive, no
numbers that look auto-incremented).

**Detection — check if an ID looks stable:**
```bash
playwright-cli eval "(() => { const el = document.querySelector('#login-form'); return el ? 'found, likely stable' : 'not found'; })()"
```

#### 3.2 Name Attribute

```python
page.locator('input[name="email"]')
page.locator('select[name="country"]')
```

**Why decent:** `name` attributes are tied to form submission and backend
processing. They rarely change because the server depends on them.

**Best for:** Form fields, especially in server-rendered apps.

#### 3.3 Stable CSS Selector Combos

```python
page.locator('form.login-form input[type="email"]')
page.locator('nav.main-nav a[href="/pricing"]')
```

**When acceptable:** When the CSS classes are semantic (`.login-form`,
`.product-card`) rather than utility-based (`.mt-4.flex.items-center`).
Combine with attribute selectors for specificity.

**Never use:** Tailwind/utility classes, dynamically generated class names
(CSS modules hashes like `.Form_input__a1b2c`), or deeply nested selectors.

---

### Tier 4 — Text-Based

#### 4.1 Exact Text Match

```python
page.get_by_text("Submit Application", exact=True)
```

**When acceptable:** For buttons and links with unique, stable copy. Works
well for CTAs that are unlikely to change frequently.

**When dangerous:** Lists of items, repeated patterns, dynamically generated
text, or text that's likely to be A/B tested.

#### 4.2 Partial Text Match

```python
page.get_by_text("Submit")  # matches any element containing "Submit"
```

**Risk:** Matches too broadly. Avoid unless scoped to a specific container.

---

### Tier 5 — Fragile (Avoid)

#### 5.1 XPath

```python
page.locator("//div[@class='container']/div[2]/form/button")
```

**Why bad:** Tightly coupled to DOM structure. Any wrapper div added, any
reorder of children, any class rename breaks it. XPath is the #1 cause of
"my automation broke after a deploy."

**Only acceptable if:** Every other option has been exhausted AND the XPath
targets a stable attribute (e.g., `//button[@data-action='submit']` — but at
that point, use a CSS selector instead).

#### 5.2 Index-Based / nth-child

```python
page.locator("button").nth(2)
page.locator("tr:nth-child(5) td:nth-child(3)")
```

**Why terrible:** Completely dependent on element order. Adding a new button
anywhere on the page shifts all indices. Never use these in production
scripts.

---

## Decision Tree

When you've inspected an element, follow this logic:

```
Does it have a data-testid (or data-test/data-cy)?
  YES → use get_by_test_id() — done
  NO  ↓

Is it a form control with an associated <label>?
  YES → use get_by_label() — done
  NO  ↓

Does it have a clear ARIA role + unique accessible name?
  YES → use get_by_role(role, name=...) — done
  NO  ↓

Does it have a unique, human-written placeholder?
  YES → use get_by_placeholder() — done
  NO  ↓

Does it have a stable, human-readable id?
  YES → use page.locator("#id") — done
  NO  ↓

Does it have a name attribute (form element)?
  YES → use page.locator('[name="..."]') — done
  NO  ↓

Can you build a short, semantic CSS selector?
  YES → use page.locator("css selector") — done
  NO  ↓

Does it have unique, stable visible text?
  YES → use get_by_text("...", exact=True) — done
  NO  ↓

Scope a higher-tier selector inside a parent:
  page.locator("#section").get_by_role("button", name="...")
  ↓

Last resort: XPath targeting an attribute (not structure)
  ALWAYS add a comment: # FRAGILE: No stable selector available
```

---

## Uniqueness Verification

Before committing to any selector in the final script, verify it matches
exactly one element:

```bash
# Check count
playwright-cli eval "document.querySelectorAll('[data-testid=\"login-btn\"]').length"

# For Playwright locators, use run-code
playwright-cli run-code "console.log(await page.get_by_test_id('login-btn').count())"
```

If the count is not 1, either:
- Scope it inside a parent container
- Add more specificity
- Move down the ladder to a more specific selector

A selector that matches 0 elements is wrong. A selector that matches 2+ is
ambiguous and will cause unpredictable behavior.

---

## Framework-Specific Notes

### React / Next.js
- IDs are often auto-generated — inspect carefully
- `data-testid` is common if the team follows testing-library conventions
- Component re-renders can change element refs — always re-snapshot

### Angular
- Look for `ng-reflect-*` attributes (but these are debug-mode only)
- Angular Material uses `mat-*` classes — stable but framework-coupled
- Prefer `aria-label` and `role` which Angular apps tend to include

### Vue
- `data-v-*` attributes are scoped CSS hashes — never use these
- Vue test utils encourage `data-testid` — check for them

### Wordpress / PHP
- IDs are often stable and human-written
- Form `name` attributes are very reliable (tied to PHP `$_POST`)
- Menu structures use semantic IDs (`#primary-nav`, `#site-header`)

### SPAs with Dynamic Routing
- URLs change without full page loads — use `wait_for_url` not `wait_for_navigation`
- Content loads async — always wait for the specific element you need, not just `networkidle`
