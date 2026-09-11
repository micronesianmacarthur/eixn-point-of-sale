# UI/UX Design Document

## 1. Introduction
This document outlines the user interface (UI) and user experience (UX) requirements for the custom Point of Sale (POS) and Inventory Management system. It is designed to guide frontend implementation using a **hybrid architecture** combining **HTMX** (for data synchronization and page structure fragments) and **Alpine.js** (for reactive interface interactions).

## 2. Global Design Principles
* **Hardware & Ergonomic Reality:** The UI must adapt to distinct physical interaction models based on the device. Handheld mobile phones rely entirely on thumb-reach touchscreens, while mounted desktop Mini-PCs utilize physical HID barcode scanners and accommodate extended index-finger tapping or keyboard shortcuts.
* **Responsive Grid Architecture:** The design system must use a strict responsive breakpoint system:
  * **Mobile/Handheld View:** A single-column layout where the active cart dominates the screen and actions are pinned to the bottom.
  * **Desktop/Tablet View:** Snaps into a two-column layout. The active cart dominates the left column, while the Quick Service Grid, Manual Search, and Customer actions stay permanently open and visible on the right column.
* **Conditional Element Rendering (RBAC):** Django template logic securely validates roles prior to execution. Restricted links (like the Admin Dashboard) are physically stripped from the HTML server-side before being injected into the DOM via HTMX.
* **High-Contrast Adaptive Theming:** The default theme must be a **High-Contrast Light Mode** to prevent glare and ensure maximum legibility. A **Dark Mode** toggle must be available, handled client-side instantly via Alpine.js global state.
* **De-escalation by Design:** System blockers (like credit limits) must use neutral colors and passive phrasing to protect cashiers from customer friction.

---

## 3. Core Interface Flows & Layouts

### 3.1 The Main POS Checkout Screen
* **Active Cart Layout:** The active cart dominates the central vertical real estate of the screen (or the left column on desktop).
* **Cart Mutation Micro-Interactions:** Each line-item row within the active cart features increment/decrement (**+ / -**) touch targets and a **Delete/Trash** icon. Clicking these utilizes HTMX attributes to trigger instant server-side updates in Django, cleanly swapping out the cart HTML chunk.
* **Fractional Quantity Interception (Tingi Flow):** When a product flagged as a variable-weight item is scanned, an Alpine.js modal interceptor instantly takes UI focus before committing to the cart. The cashier types the fractional amount (e.g., `0.25`) and hits enter, prompting HTMX to push the exact payload to the Django server draft row.
* **Sticky Checkout Footer:** The bottom of the cart view features a permanently visible sticky footer displaying the **Running Total Amount** and a massive, thumb-friendly **"Pay / Complete Checkout"** button.
* **Persistent Mobile Navigation:** On mobile screens, manual actions (Quick Service Grid, Manual Search, Lookup Customer) are exposed via a persistent bottom navigation bar managed by Alpine.js tabs, sitting just above the sticky checkout footer.
* **Predictive Customer Lookup:** Typing 2-3 letters of a customer's name inside the customer search bar triggers an automatic HTMX delayed input event (`hx-trigger="keyup changed delay:200ms"`), instantly filtering a quick-tap list of matches from Django.
* **The Tendered Cash Modal:** Clicking "Pay" triggers an Alpine.js modal opening a custom numeric keypad built directly into the UI, preventing the native OS mobile keyboard from deploying. This modal includes **"Quick Cash" shortcut buttons** (e.g., Exact Change, 10, 20, 50) that perform instant, client-side change-due calculations using Alpine variables.
* **Asynchronous Peripheral Handshaking:** When a transaction is finalized via HTMX, the peripheral print/kick request executes asynchronously. Alpine.js controls a processing spinner state on the checkout button with a strict **3-second timeout rule**. If the IP printer doesn't acknowledge within 3 seconds, Alpine throws a non-blocking toast notification: *"Printing Delayed — Receipt Saved to Queue. [Retry Print] [Skip & Clear Cart]"*.

### 3.2 "Black Book" Hard-Stop Messaging
* **Visual Cue:** If a customer exceeds their credit limit, an Alpine.js conditional block reveals a neutral, passive orange warning banner, avoiding aggressive red error boxes.
* **Exact Phrasing:** The banner must explicitly read: **"System Alert: Manager Override Required for Account Review."**

### 3.3 The Admin Dashboard
* **Hierarchy of Information:** The top-to-bottom layout is strictly ordered:
  1. **Infrastructure Indicator:** A persistent "Cloud Backup Sync Status" widget. If a backup has failed or hasn't run in over 24 hours, this widget mutates into an amber warning block stating: *"System Alert: Cloud Synchronization Offline for X Days. Check Internet Connection."*
  2. **Actionable Alerts:** "Low Stock on Fast Movers" (Red/Yellow warning cards).
  3. **Primary Revenue:** "Today's Gross Sales" (Large, highly visible typography).
  4. **Risk Exposure:** "Total Outstanding Black Book Debt" (Summary of locked capital).

### 3.4 Offline Recovery Data Entry
* **Hardware Targeting:** The Offline Recovery interface is strictly optimized for the desktop mini-PC and a physical keyboard.
* **Keyboard-Driven Spreadsheet:** A highly dense grid using Alpine.js event handling to capture keyboard navigation (e.g., hitting `Tab` or arrow keys moves instantly between cells).
* **Inline, Non-Blocking Validation:** Typos do not trigger blocking popup modals. Invalid inputs are flagged inline by Alpine.js, highlighting the specific cell border in red or orange, while errors are aggregated globally at the bottom of the grid prior to final batch submission.

---

## 4. Typography & Accessibility
* **Fonts:** Utilize clean, sans-serif system fonts optimized for UI legibility.
* **Sizing & Hierarchy:** The Running Total and the "Pay" button must feature the largest typography on the screen. Product names and prices within the active cart must scale responsively to accommodate viewing distances.
