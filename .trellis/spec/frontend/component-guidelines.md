# Component Guidelines

> How components are built in this project.

---

## Overview

<!--
Document your project's component conventions here.

Questions to answer:
- What component patterns do you use?
- How are props defined?
- How do you handle composition?
- What accessibility standards apply?
-->

(To be filled by the team)

## Dashboard Skill Bucket Contract

The `/api/v1/stats/skills` response includes a `dashboard_bucket` field. The
backend may return taxonomy categories that are not present in the frontend's
preferred display order. Consumers must preserve the preferred order for known
buckets, register non-empty buckets dynamically, and append them after the
known buckets. Treating `dashboard_bucket` as a closed frontend enum can crash
rendering when taxonomy categories evolve.

```js
if (!grouped.has(bucket)) {
  grouped.set(bucket, []);
}
grouped.get(bucket).push(skill);
```

Regression tests should include a response such as
`dashboard_bucket: "Product & Delivery"` and assert both successful rendering
and appended bucket order.

---

## Component Structure

<!-- Standard structure of a component file -->

(To be filled by the team)

---

## Props Conventions

<!-- How props should be defined and typed -->

(To be filled by the team)

---

## Styling Patterns

<!-- How styles are applied (CSS modules, styled-components, Tailwind, etc.) -->

(To be filled by the team)

---

## Accessibility

<!-- A11y requirements and patterns -->

(To be filled by the team)

---

## Common Mistakes

<!-- Component-related mistakes your team has made -->

(To be filled by the team)
