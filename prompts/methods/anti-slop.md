# AI Slop Detection

AI-generated frontend code frequently produces visually generic, cookie-cutter designs. This checklist detects and rejects common AI aesthetic anti-patterns.

## Blacklisted Patterns (flag as HIGH severity if detected)

### Layout Anti-Patterns
- **Three-column grid with colored-circle icons**: The most common AI layout cliche
- **Centered-everything layout**: No visual hierarchy, everything floats in the middle
- **Generic hero section**: Large heading + subtitle + stock-photo placeholder + CTA button
- **Symmetric card grids**: 3 or 4 identical cards with icon + title + description

### Visual Anti-Patterns
- **Purple/violet gradient backgrounds**: The default AI "modern" aesthetic
- **Decorative abstract blobs or waves**: SVG shapes that serve no informational purpose
- **Excessive rounded corners**: `border-radius: 9999px` on everything (buttons, cards, inputs)
- **Gratuitous glassmorphism**: Blur + transparency used decoratively, not functionally

### Content Anti-Patterns
- **Emoji used as design elements**: Replacing proper icons with emoji
- **Placeholder-quality copy**: "Get Started", "Learn More", "Join Us" without specific action
- **Lorem ipsum or filler text** left in production-facing components
- **Generic testimonial sections**: Circular avatar + name + company + quote template

## Check Method
1. Scan generated CSS for blacklisted properties (purple gradients, 9999px radius patterns)
2. Scan generated HTML/JSX for blacklisted structural patterns (3-col icon grids, hero templates)
3. Flag each match with severity and specific pattern name
4. Suggest concrete design alternatives for each flagged pattern

## Scoring
- **0 patterns detected**: PASS — design shows intentional choices
- **1-2 patterns with justification**: WARN — acceptable if designer-approved
- **3+ patterns**: FAIL — regenerate with explicit design constraints and brand guidelines

## What Good Looks Like
- Asymmetric layouts that create visual hierarchy
- Brand-specific color palette (not generic purple/blue gradients)
- Purposeful whitespace (not just centered with margins)
- Custom iconography or illustration style
- Typography hierarchy with intentional scale
- Interactive states that feel crafted (hover, focus, active)
