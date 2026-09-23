# OmniPort View System - Attribute Reference

This document provides a comprehensive list of tags and their supported attributes within the OmniPort framework, specifically for the Starlette presentation adapter.

## 📝 Templating Syntax

OmniPort uses a Jinja2-compatible syntax for layout inheritance and blocks:
- `{% extends "layout_name.xml" %}`: Inherits from a layout in `src/application/view/layout/`.
- `{% block block_name %}` ... `{% endblock %}`: Defines or overrides a content block.
- `{{ variable_name }}`: Injects variables from the context.
- `{{ inner | safe }}`: Injects child nodes (used in custom components).

## 🧩 Custom Components

OmniPort allows you to create reusable UI components by defining XML files in `src/application/view/component/`.

### Creating a Component
Create an XML file, for example `src/application/view/component/Card.xml`:
```xml
<Column class="p-6 bg-white rounded-xl shadow-xl border border-gray-100">
    <Text type="h3" font="bold" color="#111">{{ component.attributes.title }}</Text>
    <Divider margin="10px,0" />
    <Container>
        {{ inner | safe }}
    </Container>
</Column>
```

### Using a Component
Use the filename (without extension) as the tag name:
```xml
<Card title="Featured Product">
    <Text>This is the content inside the card.</Text>
    <Action type="button">Buy Now</Action>
</Card>
```

### Component Context
Inside a component template, you have access to:
- `component.attributes`: A dictionary of all attributes passed to the tag.
- `component.id`: The unique ID generated for this component instance.
- `{{ inner | safe }}`: Injects the nested XML children of the tag. **Required** for components that wrap other elements.

## Session Data

Do not render the complete `session` object into a page. It can contain
authentication state and other private data. Render only explicitly selected,
non-sensitive fields that the page needs.

## ⚡ Reactive WebSockets (bind)

OmniPort features a built-in server-driven reactive engine. By using the `bind` attribute, an XML element will automatically re-render and patch itself via WebSockets whenever the underlying DSL state changes.

### Basic Usage
```xml
<Text id="counter_display" bind="counter_logic.count">
    {{ counter_logic.count }}
</Text>
```

### Cross-Controller Reactivity
You can bind an element to state managed by a *completely different* DSL controller using the `alias:path` syntax.
```xml
<Text id="auth_header" bind="auth:user.name">
    Welcome back, {{ auth_state.user.name }}!
</Text>
```

### ⚠️ IMPORTANT: Explicit ID Required
If you use the `bind` attribute, **you MUST provide an explicit `id` attribute** on the same element.
```xml
<!-- ❌ WRONG: Will throw a framework Exception -->
<Container bind="cart:items.count"> ... </Container>

<!-- ✅ CORRECT: Has an explicit id -->
<Container id="cart_indicator" bind="cart:items.count"> ... </Container>
```

## 🏷️ Standard Tags

Most standard tags support a set of common attribute groups:
- **Identity**: `id`, `class`
- **Layout**: `width`, `height`, `min-width`, `max-width`, `min-height`, `max-height`, `padding`, `margin`, `overflow`, `expand`, `spacing`
- **Location**: `justify`, `align`, `position`, `top`, `bottom`, `left`, `right`
- **Style**: `background`, `matter`, `color`, `border`, `radius`, `shadow`, `thickness`, `style`

---

### `<Window>`
Main container for pages or modals.
- **Types**: `page`, `dialog`, `still`, `embed`
- **Attributes**: Identity + Location + Layout + Style + `title`, `pointer`

### `<Text>`
All text-based elements.
- **Types**: `text`, `input`, `h1`, `h2`, `h3`, `h4`, `h5`, `h6`, `p`, `span`, `mark`, `code`, `pre`, `blockquote`, `cite`, `abbr`, `time`
- **Attributes**: Style + Typography (`size`, `weight`, `uppercase`, `lowercase`, `truncate`, `font`, `align`, `spacing`, `expand`, `width`, `height`, `margin`, `padding`, `overflow`)

### `<Input>`
Form input elements.
- **Types**: `input`, `select`, `textarea`, `text`, `password`, `switch`, `checkbox`, `radio`, `range`, `color`, `date`, `month`, `week`, `time`, `number`, `email`, `url`, `search`, `tel`, `dropdown`, `file`, `hidden`
- **Attributes**: Identity + `name`, `value`, `placeholder`, `required`, `disabled`, `readonly`, `max`, `min`, `multiple`, `type`

### `<Action>`
Interactive elements like buttons or forms.
- **Types**: `form`, `action`, `button`, `submit`, `reset`, `link`
- **Attributes**: Identity + Layout + Style + `src`, `width`, `height`, `alt`, `pointer`

### `<Container>`
Basic layout box.
- **Types**: `container`, `fluid`
- **Attributes**: Identity + Layout Static + Location + Style

### `<Row>` / `<Column>` / `<Stack>`
Flexbox layout wrappers.
- **Types**: `row`, `column`, `stack`
- **Attributes**: Identity + Layout + Location + Style

### `<Divider>`
Visual separator.
- **Types**: `divider`, `vertical`, `horizontal`
- **Attributes**: Identity + Location + Layout + Style + `thickness`

### `<Icon>`
Generic icon support (Bootstrap Icons by default).
- **Types**: `icon`, `bi`, `fa`
- **Attributes**: Identity + `name` (as class), `size`, `color`

### `<Navigation>`
Navigation bars and menus.
- **Types**: `navigation`, `bar`, `app`, `breadcrumb`, `tab`
- **Attributes**: Identity + Location + Layout + Style

### `<Group>`
Grouping elements for UI components.
- **Types**: `input`, `action`, `card`, `list`, `tab`, `dropdown`
- **Attributes**: Identity + Layout + Location + Style

### `<Grid>`
Grid layout system.
- **Types**: `grid`
- **Attributes**: Identity + Layout + Style + Location

### 🎨 Color Formats
Attributes like `color` and `background` support:
- Standard Hex: `#ffffff`
- Hex with Alpha: `#000000ff`
- Hex with Transparency (Tailwind style): `#0B0E14/80` (80% opacity)
- Gradients: `#2ff801,#568dff` (comma-separated hex codes)

---

## 🎨 SVG Elements

SVG elements use a specific set of attributes mapped directly to the SVG standard.

- **Available Tags**: `<svg>`, `<g>`, `<defs>`, `<rect>`, `<circle>`, `<path>`, `<text_svg>`, `<tspan>`, `<style_svg>`, `<filter>`, `<fegaussianblur>`, `<feoffset>`, `<feflood>`, `<fecomposite>`, `<femerge>`, `<femerge_node>`, `<animate>`, `<animatetransform>`, `<stop>`, `<lineargradient>`, `<radialgradient>`, `<polygon>`, `<line>`, `<fedropshadow>`, `<clipPath>`
- **Attributes**: `id`, `class`, `style`, `viewBox`, `d`, `cx`, `cy`, `r`, `rx`, `ry`, `x`, `y`, `dx`, `dy`, `fill`, `stroke`, `stroke-width`, `transform`, `filter`, `stdDeviation`, `in`, `in2`, `operator`, `result`, `flood-color`, `flood-opacity`, `text-anchor`, `font-family`, `font-size`, `font-weight`, `font-style`, `attributeName`, `values`, `keyTimes`, `dur`, `repeatCount`, `opacity`, `points`, `offset`, `stop-color`, `stop-opacity`, `width`, `height`, `x1`, `y1`, `x2`, `y2`, `clip-path`, `clipPathUnits`, `from`, `to`, `begin`, `additive`, `accumulate`

---

## ⚡ Attribute Value Mapping (Tailwind)

Attributes are parsed and mapped to internal Tailwind-like classes:

| Attribute | Logic / Example |
| :--- | :--- |
| `width` | `full` → `w-full`, `1/2` → `w-1/2`, `100px` → `w-[100px]` |
| `height` | `full` → `h-full`, `50px` → `h-[50px]` |
| `padding` | `10px` → `p-[10px]`, `10px,20px` → `py-[10px] px-[20px]` |
| `margin` | `10px` → `m-[10px]`, `5px,10px,5px,10px` → `mt-[5px] mb-[10px] ml-[5px] mr-[10px]` |
| `background` | `#fff` → `bg-[#fff]`, `#000,#fff` → Gradient |
| `color` | `primary` → `text-primary`, `#555` → `text-[#555]` |
| `justify` | `center` → `justify-center`, `between` → `justify-between` |
| `align` | `center` → `items-center` |
| `radius` | `none`, `small` (`rounded-sm`), `medium`, `large`, `full` |
| `matter` | `glass` (`blur-md`), `glass-min` (`blur-sm`), `glass-medium` (`blur-lg`), `glass-max` (`blur-xl`) |
| `shadow` | `none`, `min` (`shadow-sm`), `medium`, `large`, `max` |
| `pointer` | `auto`, `default`, `pointer`, `wait`, `text`, `move`, `not-allowed`, `help`, `crosshair`, `grab`, `grabbing` |
| `justify` | `start`, `end`, `center`, `between`, `around`, `evenly` |
| `align` | `start`, `end`, `center`, `stretch` |
| `font` | `bold` → `font-bold`, `mono` → `font-mono` |

---

## 🏗️ Layout Inheritance & Blocks
When using `{% extends %}`, common layout files in `src/application/view/layout/` provide these blocks:
- `{% block main %}`: The primary content area for a page.
- `{% block content %}`: Content area within sidebar/app layouts.
- `{% block bar %}`: Header or navigation specific blocks.

### 💡 Pro Tips:
- **Raw CSS**: If a specific style is missing, use the `style` attribute for inline CSS.