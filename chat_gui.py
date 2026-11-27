"""Chat window for the grocery agent.

The window runs the same steps as main.py:
    1. agent.generate_meal_plan()      - the chat with the user
    2. agent.generate_shopping_list()  - what to buy, after removing pantry items

The agent code is not changed for the GUI. generate_meal_plan() takes an input_fn and an output_fn, so the
GUI passes its own versions: input_fn waits for the user to type in the chat box, and
output_fn shows the agent's messages in the chat box. The agent runs on a worker thread
so the window stays responsive while the model is working.

The look is meant to feel like a friendly kitchen helper rather than a tool:
warm colors, chat bubbles, tap-to-answer suggestions, the meal plan as day cards,
and a shopping list you can tick off while you shop.
"""
import logging
import queue
import re
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from config import config
from ingredient_match import pantry_match
from pantry import load_pantry, save_pantry

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Colors: a warm, kitchen-like palette.
# ----------------------------------------------------------------------
BG_WINDOW = "#F4EEE3"       # soft cream behind everything
BG_CARD = "#FFFDF9"         # white-ish cards
BG_SOFT = "#F7F2E9"         # light fill for rows and the assistant's bubbles
BORDER = "#E6DCCB"
TEXT_MAIN = "#3D3A35"
TEXT_MUTED = "#8C8478"
GREEN = "#5E8C5B"           # main accent (sage green)
GREEN_DARK = "#4B7349"
GREEN_LIGHT = "#E8F0E4"
USED_HOVER_BG = "#D9E7D3"   # hover color for pantry items the plan uses
TERRACOTTA = "#C2654A"      # things to buy
DISABLED_BG = "#E9E3D8"
DISABLED_FG = "#B3AA9C"

USER_BUBBLE_BG = GREEN
USER_BUBBLE_FG = "#FFFFFF"
ASSISTANT_BUBBLE_BG = BG_SOFT
ASSISTANT_BUBBLE_FG = TEXT_MAIN
ASSISTANT_AVATAR = "🍳"

# ----------------------------------------------------------------------
# Fonts. Tk falls back to the system font if one is not installed.
# ----------------------------------------------------------------------
TITLE_FONT = ("Georgia", 24, "bold")
HEADING_FONT = ("Georgia", 17, "bold")
DAY_FONT = ("Georgia", 15, "bold")
BODY_FONT = ("Helvetica", 14)
BODY_BOLD_FONT = ("Helvetica", 14, "bold")
SMALL_FONT = ("Helvetica", 12)
SMALL_BOLD_FONT = ("Helvetica", 11, "bold")
BUTTON_FONT = ("Helvetica", 13, "bold")
EMOJI_FONT = ("Helvetica", 22)

# ----------------------------------------------------------------------
# Reading the agent's messages.
# ----------------------------------------------------------------------
# The agent prefixes model replies with this (see Agent._ask in agent.py).
ANSWER_PREFIX = "Answer:"

# A model reply that contains a meal plan: a JSON list of objects (same check as
# check_meal_plan in meal_plan.py). The plan itself is shown as cards, not as JSON.
PLAN_START = re.compile(r"\[\s*\{")

# Behind-the-scenes agent messages, turned into friendly words (or hidden).
PLAN_REJECTED_PREFIX = "Meal plan rejected"
PLAN_ACCEPTED_PREFIX = "Meal plan generated"
PLAN_FAILED_PREFIX = "Could not get a valid meal plan"
MODEL_MISSING_PREFIX = "MLX model generation is not available"

# What the "thinking" bubble says while the agent is busy.
THINKING_LABELS = {
    "Starting": "Getting ready",
    "Loading model": "Warming up the kitchen",
    "Thinking": "Thinking",
    "Building shopping list": "Writing your shopping list",
}

# ----------------------------------------------------------------------
# Tap-to-answer suggestions: (button text, message sent to the agent).
# ----------------------------------------------------------------------
DAY_SUGGESTIONS = [
    ("3 days", "3 days"),
    ("5 days", "5 days"),
    ("A whole week", "7 days"),
]
PREFERENCE_SUGGESTIONS = [
    ("🥦 Vegetarian", "Vegetarian meals, please."),
    ("⚡ Quick & easy", "Quick and easy meals, 30 minutes or less."),
    ("🧒 Kid-friendly", "Kid-friendly meals that children will enjoy."),
    ("💰 Budget-friendly", "Budget-friendly meals, please."),
    ("🎲 Surprise me", "No special requests - surprise me!"),
]

# Icons for each meal of the day.
MEAL_ICONS = {
    "breakfast": "🍳",
    "brunch": "🥞",
    "lunch": "🥗",
    "dinner": "🍲",
    "supper": "🍲",
    "snack": "🍎",
    "dessert": "🍰",
}

# How wide text may get, as a share of the chat area's width.
BUBBLE_WIDTH_SHARE = 0.62
CARD_TEXT_WIDTH_SHARE = 0.72

# Frames for the "thinking" animation.
THINKING_FRAMES = ["🥕", "🥦", "🍅", "🧀", "🍞", "🥚"]
THINKING_DOTS = ["", ".", "..", "..."]
ANIMATION_DELAY_MS = 180
EVENT_POLL_MS = 100


def greeting_for_now():
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning!"
    if hour < 18:
        return "Good afternoon!"
    return "Good evening!"


# ======================================================================
# Small reusable widgets
# ======================================================================

class PillButton(tk.Label):
    """A colored, clickable button.

    Built from a Label because tk.Button ignores custom colors on macOS.
    """

    def __init__(self, parent, text, command, bg=GREEN, fg="#FFFFFF",
                 hover_bg=GREEN_DARK, font=BUTTON_FONT, padx=18, pady=9, border=None):
        super().__init__(parent, text=text, bg=bg, fg=fg, font=font,
                         padx=padx, pady=pady, cursor="hand2")
        if border:
            self.config(highlightbackground=border, highlightthickness=1)
        self.command = command
        self.normal_bg = bg
        self.normal_fg = fg
        self.hover_bg = hover_bg
        self.enabled = True
        self.bind("<Button-1>", self.on_click)
        self.bind("<Enter>", self.on_hover)
        self.bind("<Leave>", self.on_leave)

    def on_click(self, _event=None):
        if self.enabled:
            self.command()

    def on_hover(self, _event=None):
        if self.enabled:
            self.config(bg=self.hover_bg)

    def on_leave(self, _event=None):
        if self.enabled:
            self.config(bg=self.normal_bg)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if enabled:
            self.config(bg=self.normal_bg, fg=self.normal_fg, cursor="hand2")
        else:
            self.config(bg=DISABLED_BG, fg=DISABLED_FG, cursor="arrow")


class PlaceholderEntry(tk.Entry):
    """A text box that shows grey hint text while it is empty."""

    def __init__(self, parent, placeholder, **options):
        super().__init__(parent, **options)
        self.placeholder = placeholder
        self.showing_placeholder = False
        self.bind("<FocusIn>", self.hide_placeholder)
        self.bind("<FocusOut>", self.show_placeholder_if_empty)
        self.show_placeholder_if_empty()

    def hide_placeholder(self, _event=None):
        if self.showing_placeholder:
            self.delete(0, "end")
            self.config(fg=TEXT_MAIN)
            self.showing_placeholder = False

    def show_placeholder_if_empty(self, _event=None):
        if self.get() == "" and self.focus_get() is not self:
            self.insert(0, self.placeholder)
            self.config(fg=TEXT_MUTED)
            self.showing_placeholder = True

    def set_placeholder(self, text):
        self.placeholder = text
        if self.showing_placeholder:
            old_state = self.cget("state")
            self.config(state="normal")
            self.delete(0, "end")
            self.insert(0, text)
            self.config(state=old_state)

    def get_text(self):
        if self.showing_placeholder:
            return ""
        return self.get().strip()

    def set_text(self, text):
        self.hide_placeholder()
        self.delete(0, "end")
        self.insert(0, text)

    def clear(self):
        self.delete(0, "end")
        self.showing_placeholder = False
        self.show_placeholder_if_empty()


class ScrollableFrame(tk.Frame):
    """A frame with a vertical scrollbar. Put content inside self.inner."""

    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner.bind("<Configure>", self.update_scroll_region)
        self.canvas.bind("<Configure>", self.match_inner_width)

    def update_scroll_region(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def match_inner_width(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def contains(self, widget):
        """True if widget is this frame's canvas or anything inside it."""
        return str(widget).startswith(str(self.canvas))

    def scroll(self, steps):
        # Nothing to scroll when everything already fits.
        if self.canvas.yview() == (0.0, 1.0):
            return
        self.canvas.yview_scroll(steps, "units")

    def scroll_to_bottom(self):
        self.canvas.update_idletasks()
        self.update_scroll_region()
        self.canvas.yview_moveto(1.0)


def pantry_items_used(ingredients, pantry_items):
    """The pantry items that a meal's ingredients use, in pantry order.

    Uses the same rule as the agent's shopping-list filter: only a clear match counts,
    so 'chicken breasts' uses 'chicken breast', but 'brown rice' does not use 'rice'.
    """
    used = []
    for pantry_item in pantry_items:
        for ingredient in ingredients:
            if isinstance(ingredient, str) and pantry_match(ingredient, pantry_item) == "leak":
                used.append(pantry_item)
                break
    return used


# ======================================================================
# The main window
# ======================================================================

class GroceryAgentChatGUI:
    """Chat with the meal planner, with "My Kitchen" (the pantry) on the side."""

    def __init__(self, root):
        self.root = root
        self.root.title("Meal Planner")
        self.root.geometry("1200x840")
        self.root.minsize(900, 620)
        self.root.configure(bg=BG_WINDOW)

        self.agent = None
        # Worker thread -> UI: (event_name, data) tuples. See handle_event().
        self.events = queue.Queue()
        # UI -> worker thread: what the user typed, read by the agent's input_fn.
        self.user_replies = queue.Queue()

        self.session_running = False
        self.waiting_for_user = False
        self.replies_this_session = 0

        self.animation_running = False
        self.animation_label = "Thinking"
        self.animation_step = 0
        self.animation_timer = None
        self.thinking_row = None
        self.thinking_text = None

        # Labels whose wrap width follows the chat width: (label, share of width).
        self.wrapping_labels = []
        # Index of the pantry item being renamed, or None when adding.
        self.editing_index = None
        # Lowercased names of the pantry items the current meal plan cooks with.
        self.pantry_items_in_plan = set()

        self.build_ui()
        self.refresh_pantry_list()
        self.bind_mouse_wheel()
        self.poll_events()
        self.start_session()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def build_ui(self):
        outer = tk.Frame(self.root, bg=BG_WINDOW)
        outer.pack(fill="both", expand=True, padx=24, pady=24)

        # "My Kitchen" on the left, the chat fills the rest on the right.
        kitchen_card = self.make_card(outer)
        kitchen_card.config(width=310)
        kitchen_card.pack_propagate(False)
        kitchen_card.pack(side="left", fill="y", padx=(0, 20))
        self.build_kitchen_panel(kitchen_card)

        chat_card = self.make_card(outer)
        chat_card.pack(side="right", fill="both", expand=True)
        self.build_chat_panel(chat_card)

    def make_card(self, parent):
        return tk.Frame(parent, bg=BG_CARD, highlightbackground=BORDER,
                        highlightthickness=1, padx=22, pady=20)

    def make_text_entry(self, parent, placeholder):
        return PlaceholderEntry(
            parent,
            placeholder,
            font=BODY_FONT,
            relief="flat",
            bg="#FFFFFF",
            fg=TEXT_MAIN,
            disabledbackground=BG_SOFT,
            disabledforeground=TEXT_MUTED,
            insertbackground=TEXT_MAIN,
            highlightbackground=BORDER,
            highlightcolor=GREEN,
            highlightthickness=2,
        )

    def build_chat_panel(self, card):
        # Header: a friendly greeting and a "new plan" button.
        header = tk.Frame(card, bg=BG_CARD)
        header.pack(fill="x", pady=(0, 14))

        title_block = tk.Frame(header, bg=BG_CARD)
        title_block.pack(side="left")
        tk.Label(title_block, text=f"{greeting_for_now()} 🌿", font=TITLE_FONT,
                 fg=TEXT_MAIN, bg=BG_CARD).pack(anchor="w")
        tk.Label(title_block, text="Let's plan your meals together - I'll write the shopping list for you.",
                 font=SMALL_FONT, fg=TEXT_MUTED, bg=BG_CARD).pack(anchor="w", pady=(4, 0))

        self.new_plan_button = PillButton(
            header, "＋  New meal plan", self.start_session,
            bg=GREEN_LIGHT, fg=GREEN_DARK, hover_bg="#D9E7D3",
        )
        self.new_plan_button.pack(side="right", anchor="n")

        # Bottom area, packed before the chat so it always stays visible.
        bottom = tk.Frame(card, bg=BG_CARD)
        bottom.pack(side="bottom", fill="x", pady=(14, 0))

        self.suggestion_bar = tk.Frame(bottom, bg=BG_CARD)
        self.suggestion_bar.pack(fill="x", pady=(0, 10))

        input_row = tk.Frame(bottom, bg=BG_CARD)
        input_row.pack(fill="x")
        self.user_input = self.make_text_entry(input_row, "Type your answer here...")
        self.user_input.pack(side="left", fill="x", expand=True, ipady=11)
        self.user_input.bind("<Return>", self.on_submit)

        self.send_button = PillButton(input_row, "Send  ➤", self.send_message, pady=11)
        self.send_button.pack(side="right", padx=(10, 0))

        # The conversation itself.
        self.chat = ScrollableFrame(card, BG_CARD)
        self.chat.pack(fill="both", expand=True)
        self.chat.canvas.bind("<Configure>", self.on_chat_resize, add="+")

    def build_kitchen_panel(self, card):
        tk.Label(card, text="🧺 My Kitchen", font=HEADING_FONT, fg=TEXT_MAIN,
                 bg=BG_CARD).pack(anchor="w")
        tk.Label(card, text="Things you already have at home.\nI'll leave them off your shopping list.",
                 font=SMALL_FONT, fg=TEXT_MUTED, bg=BG_CARD, justify="left").pack(anchor="w", pady=(4, 12))

        # Add / rename box at the bottom.
        bottom = tk.Frame(card, bg=BG_CARD)
        bottom.pack(side="bottom", fill="x", pady=(12, 0))

        self.pantry_entry = self.make_text_entry(bottom, "Add an item, e.g. eggs")
        self.pantry_entry.pack(fill="x", ipady=8)
        self.pantry_entry.bind("<Return>", lambda _event: self.save_pantry_entry())

        button_row = tk.Frame(bottom, bg=BG_CARD)
        button_row.pack(fill="x", pady=(8, 0))
        self.pantry_save_button = PillButton(button_row, "＋ Add", self.save_pantry_entry, pady=7)
        self.pantry_save_button.pack(side="left")
        self.pantry_cancel_button = PillButton(
            button_row, "Cancel", self.stop_editing_pantry_item,
            bg=BG_CARD, fg=TEXT_MUTED, hover_bg=BG_SOFT, pady=7,
        )
        # The cancel button is only shown while renaming an item.

        self.pantry_status = tk.Label(bottom, text="", font=SMALL_FONT, fg=GREEN_DARK,
                                      bg=BG_CARD, anchor="w", justify="left", wraplength=260)
        self.pantry_status.pack(fill="x", pady=(8, 0))

        self.pantry_count = tk.Label(card, text="", font=SMALL_BOLD_FONT, fg=TEXT_MUTED,
                                     bg=BG_CARD, anchor="w")
        self.pantry_count.pack(fill="x", pady=(0, 6))

        self.pantry_list = ScrollableFrame(card, BG_CARD)
        self.pantry_list.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Scrolling and resizing
    # ------------------------------------------------------------------

    def bind_mouse_wheel(self):
        self.root.bind_all("<MouseWheel>", self.on_mouse_wheel)
        # Linux sends scroll events as button 4 (up) and 5 (down).
        self.root.bind_all("<Button-4>", lambda event: self.scroll_area_under(event, -1))
        self.root.bind_all("<Button-5>", lambda event: self.scroll_area_under(event, 1))

    def on_mouse_wheel(self, event):
        if sys.platform == "darwin":
            steps = -event.delta
        else:
            steps = -event.delta // 120
        self.scroll_area_under(event, steps)

    def scroll_area_under(self, event, steps):
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return
        for area in (self.chat, self.pantry_list):
            if area.contains(widget):
                area.scroll(steps)
                return

    def on_chat_resize(self, event):
        still_shown = []
        for label, share in self.wrapping_labels:
            if label.winfo_exists():
                label.config(wraplength=int(event.width * share))
                still_shown.append((label, share))
        self.wrapping_labels = still_shown

    def make_wrapping_label(self, parent, share, **options):
        """A label whose text wraps at a share of the chat width."""
        label = tk.Label(parent, justify="left", anchor="w", **options)
        chat_width = max(self.chat.canvas.winfo_width(), 600)
        label.config(wraplength=int(chat_width * share))
        self.wrapping_labels.append((label, share))
        return label

    # ------------------------------------------------------------------
    # My Kitchen (pantry editing)
    # The agent reads data/pantry.json when it starts a meal plan and when it
    # builds the shopping list, so edits made here are used by the next plan.
    # ------------------------------------------------------------------

    def refresh_pantry_list(self):
        for child in self.pantry_list.inner.winfo_children():
            child.destroy()

        items = load_pantry()
        if len(items) == 1:
            count_text = "1 ITEM"
        else:
            count_text = f"{len(items)} ITEMS"

        used_count = 0
        for item in items:
            if self.is_used_in_plan(item):
                used_count += 1
        if used_count:
            count_text += f"  ·  🍳 {used_count} IN THIS PLAN"
        self.pantry_count.config(text=count_text)

        if not items:
            tk.Label(self.pantry_list.inner,
                     text="Nothing here yet.\nAdd what's in your fridge\nand cupboards below.",
                     font=SMALL_FONT, fg=TEXT_MUTED, bg=BG_CARD, justify="center").pack(pady=30)
            return

        for index, item in enumerate(items):
            self.make_pantry_row(index, item)

    def is_used_in_plan(self, item):
        return item.strip().lower() in self.pantry_items_in_plan

    def make_pantry_row(self, index, item):
        # Items the current meal plan cooks with are shown in green with a pan icon.
        if self.is_used_in_plan(item):
            row_color = GREEN_LIGHT
            hover_color = USED_HOVER_BG
            name_text = f"🍳  {item}"
            name_font = BODY_BOLD_FONT
            name_color = GREEN_DARK
        else:
            row_color = BG_SOFT
            hover_color = GREEN_LIGHT
            name_text = item
            name_font = BODY_FONT
            name_color = TEXT_MAIN

        row = tk.Frame(self.pantry_list.inner, bg=row_color, padx=10, pady=6)
        row.pack(fill="x", pady=2, padx=(0, 6))

        name = tk.Label(row, text=name_text, font=name_font, fg=name_color, bg=row_color, anchor="w")
        name.pack(side="left", fill="x", expand=True)

        remove = tk.Label(row, text="✕", font=SMALL_BOLD_FONT, fg=TEXT_MUTED, bg=row_color,
                          cursor="hand2", padx=4)
        remove.pack(side="right")
        remove.bind("<Button-1>", lambda _event: self.remove_pantry_item(index))

        rename = tk.Label(row, text="✎", font=SMALL_FONT, fg=TEXT_MUTED, bg=row_color,
                          cursor="hand2", padx=4)
        rename.pack(side="right")
        rename.bind("<Button-1>", lambda _event: self.start_editing_pantry_item(index, item))

        # Clicking the name also starts renaming; the row lights up under the mouse.
        name.bind("<Button-1>", lambda _event: self.start_editing_pantry_item(index, item))
        for widget in (row, name, remove, rename):
            widget.bind("<Enter>", lambda _event: self.color_row(row, hover_color), add="+")
            widget.bind("<Leave>", lambda _event: self.color_row(row, row_color), add="+")

    def color_row(self, row, color):
        row.config(bg=color)
        for child in row.winfo_children():
            child.config(bg=color)

    def show_pantry_status(self, text, is_problem=False):
        if is_problem:
            self.pantry_status.config(text=text, fg=TERRACOTTA)
        else:
            self.pantry_status.config(text=text, fg=GREEN_DARK)

    def start_editing_pantry_item(self, index, item):
        self.editing_index = index
        self.pantry_entry.set_text(item)
        self.pantry_entry.focus_set()
        self.pantry_save_button.config(text="✓ Save")
        self.pantry_cancel_button.pack(side="left", padx=(6, 0))
        self.show_pantry_status(f"Renaming '{item}'")

    def stop_editing_pantry_item(self):
        self.editing_index = None
        self.pantry_entry.clear()
        self.pantry_save_button.config(text="＋ Add")
        self.pantry_cancel_button.pack_forget()
        self.show_pantry_status("")

    def save_pantry_entry(self):
        if self.editing_index is None:
            self.add_pantry_item()
        else:
            self.rename_pantry_item()

    def save_pantry_items(self, items, status_text):
        try:
            save_pantry(items)
        except Exception as error:
            self.show_pantry_status(f"Sorry, I couldn't save that: {error}", is_problem=True)
            return
        self.stop_editing_pantry_item()
        self.refresh_pantry_list()
        self.show_pantry_status(status_text)

    def is_in_pantry(self, items, name):
        for item in items:
            if item.lower() == name.lower():
                return True
        return False

    def add_pantry_item(self):
        new_item = self.pantry_entry.get_text()
        if not new_item:
            self.show_pantry_status("Type what you have first, e.g. eggs.", is_problem=True)
            return
        items = load_pantry()
        if self.is_in_pantry(items, new_item):
            self.show_pantry_status(f"You already have {new_item} listed.", is_problem=True)
            return
        items.append(new_item)
        self.save_pantry_items(items, f"✓ Added {new_item}")
        self.pantry_list.scroll_to_bottom()

    def rename_pantry_item(self):
        new_name = self.pantry_entry.get_text()
        if not new_name:
            self.show_pantry_status("Type the new name first.", is_problem=True)
            return
        items = load_pantry()
        if self.editing_index >= len(items):
            self.stop_editing_pantry_item()
            return
        old_name = items[self.editing_index]
        items[self.editing_index] = new_name
        self.save_pantry_items(items, f"✓ Changed {old_name} to {new_name}")

    def remove_pantry_item(self, index):
        items = load_pantry()
        if index >= len(items):
            return
        removed = items.pop(index)
        self.save_pantry_items(items, f"✓ Removed {removed}")

    # ------------------------------------------------------------------
    # Chat display
    # ------------------------------------------------------------------

    def add_chat_row(self, row, pady=6):
        """Show a row in the chat, keeping the thinking bubble as the last row."""
        if self.thinking_row is not None:
            row.pack(fill="x", pady=pady, before=self.thinking_row)
        else:
            row.pack(fill="x", pady=pady)
        self.chat.scroll_to_bottom()

    def make_bubble_row(self, sender, text):
        """A chat bubble: the user's on the right in green, the assistant's on the left."""
        row = tk.Frame(self.chat.inner, bg=BG_CARD)
        if sender == "user":
            bubble = self.make_wrapping_label(
                row, BUBBLE_WIDTH_SHARE, text=text, font=BODY_FONT,
                bg=USER_BUBBLE_BG, fg=USER_BUBBLE_FG, padx=16, pady=10,
            )
            bubble.pack(side="right", padx=(80, 8))
        else:
            avatar = tk.Label(row, text=ASSISTANT_AVATAR, font=EMOJI_FONT, bg=BG_CARD)
            avatar.pack(side="left", anchor="n", padx=(4, 8))
            bubble = self.make_wrapping_label(
                row, BUBBLE_WIDTH_SHARE, text=text, font=BODY_FONT,
                bg=ASSISTANT_BUBBLE_BG, fg=ASSISTANT_BUBBLE_FG, padx=16, pady=10,
            )
            bubble.pack(side="left", padx=(0, 80))
        return row, bubble

    def add_message(self, sender, text, widget_builder=None):
        """Add a chat bubble. widget_builder, if given, builds a card shown below it."""
        row, _ = self.make_bubble_row(sender, text)
        self.add_chat_row(row)
        if widget_builder is not None:
            card_row = tk.Frame(self.chat.inner, bg=BG_CARD)
            widget_builder(card_row).pack(fill="x", padx=(52, 24))
            self.add_chat_row(card_row, pady=(0, 10))

    def add_note(self, text):
        """A small grey line in the middle of the chat, for quiet updates."""
        row = tk.Frame(self.chat.inner, bg=BG_CARD)
        tk.Label(row, text=text, font=SMALL_FONT, fg=TEXT_MUTED, bg=BG_CARD).pack()
        self.add_chat_row(row, pady=12)

    def start_thinking_animation(self, label="Thinking"):
        self.animation_label = THINKING_LABELS.get(label, label)
        if self.animation_running:
            return
        self.animation_running = True
        row, bubble = self.make_bubble_row("assistant", "")
        bubble.config(fg=TEXT_MUTED, font=(BODY_FONT[0], BODY_FONT[1], "italic"))
        self.add_chat_row(row)
        self.thinking_row = row
        self.thinking_text = bubble
        self.animate()

    def stop_thinking_animation(self):
        if not self.animation_running:
            return
        self.animation_running = False
        if self.animation_timer is not None:
            self.root.after_cancel(self.animation_timer)
            self.animation_timer = None
        self.thinking_row.destroy()
        self.thinking_row = None
        self.thinking_text = None

    def animate(self):
        if not self.animation_running:
            return
        food = THINKING_FRAMES[(self.animation_step // 3) % len(THINKING_FRAMES)]
        dots = THINKING_DOTS[self.animation_step % len(THINKING_DOTS)]
        self.thinking_text.config(text=f"{food}  {self.animation_label}{dots}")
        self.animation_step += 1
        self.animation_timer = self.root.after(ANIMATION_DELAY_MS, self.animate)

    def show_suggestions(self, suggestions):
        """Replace the tap-to-answer buttons. suggestions: list of (text, command)."""
        for child in self.suggestion_bar.winfo_children():
            child.destroy()
        for text, command in suggestions:
            chip = PillButton(
                self.suggestion_bar, text, command,
                bg="#FFFFFF", fg=GREEN_DARK, hover_bg=GREEN_LIGHT,
                font=SMALL_BOLD_FONT, padx=14, pady=6, border=BORDER,
            )
            chip.pack(side="left", padx=(0, 8))

    def suggestions_for_now(self):
        if not self.session_running:
            return [("🍽️  Plan more meals", self.start_session)]
        if not self.waiting_for_user:
            return []
        if self.replies_this_session == 0:
            choices = DAY_SUGGESTIONS
        else:
            choices = PREFERENCE_SUGGESTIONS

        suggestions = []
        for text, message in choices:
            # message=message keeps each button's own message (not the loop's last one).
            suggestions.append((text, lambda message=message: self.send_text(message)))
        return suggestions

    def update_controls(self):
        """Enable typing only while the agent is waiting for the user."""
        if self.waiting_for_user:
            self.user_input.config(state="normal")
            self.user_input.set_placeholder("Type your answer here...")
            self.send_button.set_enabled(True)
            self.user_input.focus_set()
        else:
            self.user_input.set_placeholder("One moment please...")
            self.user_input.config(state="disabled")
            self.send_button.set_enabled(False)

        self.new_plan_button.set_enabled(not self.session_running)
        self.show_suggestions(self.suggestions_for_now())

    # ------------------------------------------------------------------
    # Talking to the user (called by the UI thread)
    # ------------------------------------------------------------------

    def send_message(self):
        self.send_text(self.user_input.get_text())

    def send_text(self, text):
        if not self.waiting_for_user or not text:
            return
        self.add_message("user", text)
        self.user_input.clear()
        self.waiting_for_user = False
        self.replies_this_session += 1
        self.update_controls()
        self.start_thinking_animation("Thinking")
        self.user_replies.put(text)

    def on_submit(self, _event=None):
        self.send_message()
        return "break"

    def poll_events(self):
        """Show whatever the worker thread has sent since the last check."""
        while True:
            try:
                event_name, data = self.events.get_nowait()
            except queue.Empty:
                break
            self.handle_event(event_name, data)
        self.root.after(EVENT_POLL_MS, self.poll_events)

    def handle_event(self, event_name, data):
        if event_name == "agent_output":
            self.show_agent_output(data)
        elif event_name == "waiting_for_user":
            self.stop_thinking_animation()
            self.waiting_for_user = True
            self.update_controls()
        elif event_name == "status":
            self.start_thinking_animation(data)
        elif event_name == "meal_plan":
            meal_plan, to_buy_per_meal, pantry_list = data
            self.show_meal_plan(meal_plan, to_buy_per_meal, pantry_list)
        elif event_name == "shopping_list":
            self.show_shopping_list(data)
        elif event_name == "error":
            self.stop_thinking_animation()
            self.add_message("assistant", "Oh dear, something went wrong on my side. "
                                          "Please try starting a new meal plan.")
            self.add_note(data)
        elif event_name == "session_done":
            self.stop_thinking_animation()
            self.session_running = False
            self.waiting_for_user = False
            self.update_controls()
            self.add_note("Whenever you're ready, tap 'Plan more meals' to start again.")

    def show_agent_output(self, text):
        if text.startswith(ANSWER_PREFIX):
            self.show_model_answer(text[len(ANSWER_PREFIX):].strip())
        elif text.startswith(PLAN_REJECTED_PREFIX):
            # The agent is fixing its own plan; the user only needs to know we're busy.
            logger.info(text)
            self.start_thinking_animation("Tidying up the plan")
        elif text.startswith(PLAN_ACCEPTED_PREFIX):
            # The plan cards follow straight after, so no message is needed.
            logger.info(text)
        elif text.startswith(PLAN_FAILED_PREFIX):
            logger.warning(text)
            self.add_message("assistant", "Sorry, I got a little muddled putting that plan together. "
                                          "Could you tell me again, maybe in a different way?")
        elif text.startswith(MODEL_MISSING_PREFIX):
            self.add_message("assistant", "I can't come up with meals right now - the meal planner "
                                          "isn't set up on this computer yet.")
        else:
            self.add_message("assistant", text)

    def show_model_answer(self, answer):
        plan_start = PLAN_START.search(answer)
        if plan_start is None:
            self.add_message("assistant", answer)
            return
        # Hide the JSON. If the plan is valid it is shown as cards once the agent
        # accepts it; if not, the agent quietly asks the model to fix it.
        text_before_plan = answer[:plan_start.start()].strip()
        if text_before_plan:
            self.add_message("assistant", text_before_plan)
        self.start_thinking_animation("Putting your plan together")

    # ------------------------------------------------------------------
    # Meal plan cards
    # ------------------------------------------------------------------

    def show_meal_plan(self, meal_plan, to_buy_per_meal, pantry_list):
        # Which pantry items each meal cooks with, for the meal cards and "My Kitchen".
        pantry_used_per_meal = []
        self.pantry_items_in_plan = set()
        for meal in meal_plan:
            used = pantry_items_used(meal.get("ingredients", []), pantry_list or [])
            pantry_used_per_meal.append(used)
            for item in used:
                self.pantry_items_in_plan.add(item.strip().lower())
        self.refresh_pantry_list()

        def build(parent):
            return self.build_meal_plan_cards(parent, meal_plan, to_buy_per_meal, pantry_used_per_meal)
        self.add_message("assistant", "Here's your meal plan! 🍽️", widget_builder=build)

    def group_meals_by_day(self, meal_plan, to_buy_per_meal):
        """[(day, [(meal, to_buy), ...]), ...] in the order the days appear."""
        days = []
        meals_for_day = {}
        for meal, to_buy in zip(meal_plan, to_buy_per_meal):
            day = str(meal.get("day", "")) or "Your meals"
            if day not in meals_for_day:
                meals_for_day[day] = []
                days.append(day)
            meals_for_day[day].append((meal, to_buy))

        grouped = []
        for day in days:
            grouped.append((day, meals_for_day[day]))
        return grouped

    def build_meal_plan_cards(self, parent, meal_plan, to_buy_per_meal, pantry_used_per_meal):
        # Each meal travels with its own "to buy" and "from your kitchen" lists.
        extras_per_meal = []
        for to_buy, pantry_used in zip(to_buy_per_meal, pantry_used_per_meal):
            extras_per_meal.append((to_buy, pantry_used))

        cards = tk.Frame(parent, bg=BG_CARD)
        for day, meals in self.group_meals_by_day(meal_plan, extras_per_meal):
            day_card = tk.Frame(cards, bg="#FFFFFF", highlightbackground=BORDER,
                                highlightthickness=1, padx=18, pady=14)
            day_card.pack(fill="x", pady=6)
            tk.Label(day_card, text=f"📅  {day}", font=DAY_FONT, fg=GREEN_DARK,
                     bg="#FFFFFF").pack(anchor="w", pady=(0, 4))
            for meal, (to_buy, pantry_used) in meals:
                self.add_meal_row(day_card, meal, to_buy, pantry_used)
        return cards

    def add_meal_row(self, day_card, meal, to_buy, pantry_used):
        meal_type = str(meal.get("meal_type", "")).strip()
        icon = MEAL_ICONS.get(meal_type.lower(), "🍽️")

        row = tk.Frame(day_card, bg="#FFFFFF")
        row.pack(fill="x", pady=(10, 0))
        tk.Label(row, text=icon, font=EMOJI_FONT, bg="#FFFFFF").pack(side="left", anchor="n", padx=(0, 12))

        details = tk.Frame(row, bg="#FFFFFF")
        details.pack(side="left", fill="x", expand=True)

        if meal_type:
            tk.Label(details, text=meal_type.upper(), font=SMALL_BOLD_FONT, fg=TEXT_MUTED,
                     bg="#FFFFFF").pack(anchor="w")
        self.make_wrapping_label(details, CARD_TEXT_WIDTH_SHARE, text=meal.get("meal_name", ""),
                                 font=BODY_BOLD_FONT, fg=TEXT_MAIN, bg="#FFFFFF").pack(anchor="w")

        ingredients = ", ".join(meal.get("ingredients", []))
        if ingredients:
            self.make_wrapping_label(details, CARD_TEXT_WIDTH_SHARE, text=ingredients,
                                     font=SMALL_FONT, fg=TEXT_MUTED, bg="#FFFFFF").pack(anchor="w", pady=(2, 0))

        if pantry_used:
            self.make_wrapping_label(details, CARD_TEXT_WIDTH_SHARE,
                                     text="🍳  From your kitchen: " + ", ".join(pantry_used),
                                     font=SMALL_BOLD_FONT, fg=GREEN_DARK, bg="#FFFFFF").pack(anchor="w", pady=(4, 0))

        if to_buy:
            to_buy_text = "🛒  To buy: " + ", ".join(to_buy)
            to_buy_color = TERRACOTTA
        else:
            to_buy_text = "✓  You have everything for this one"
            to_buy_color = GREEN
        self.make_wrapping_label(details, CARD_TEXT_WIDTH_SHARE, text=to_buy_text,
                                 font=SMALL_BOLD_FONT, fg=to_buy_color, bg="#FFFFFF").pack(anchor="w", pady=(4, 0))

    # ------------------------------------------------------------------
    # Shopping list (tick items off while shopping)
    # ------------------------------------------------------------------

    def show_shopping_list(self, shopping_list):
        if not shopping_list:
            self.add_message("assistant", "Good news - you already have everything you need! 🎉 "
                                          "No shopping trip this time.")
            return

        def build(parent):
            return self.build_shopping_list_card(parent, shopping_list)
        self.add_message("assistant", "And here's your shopping list. Tap an item to tick it off. 🧾",
                         widget_builder=build)

    def build_shopping_list_card(self, parent, shopping_list):
        card = tk.Frame(parent, bg="#FFFFFF", highlightbackground=BORDER,
                        highlightthickness=1, padx=18, pady=14)

        header = tk.Frame(card, bg="#FFFFFF")
        header.pack(fill="x", pady=(0, 6))
        tk.Label(header, text=f"🛒  Shopping list · {len(shopping_list)} items", font=DAY_FONT,
                 fg=TERRACOTTA, bg="#FFFFFF").pack(side="left")

        copy_button = PillButton(header, "Copy list", lambda: None,
                                 bg=BG_SOFT, fg=TEXT_MAIN, hover_bg=BORDER,
                                 font=SMALL_BOLD_FONT, padx=12, pady=5)
        copy_button.command = lambda: self.copy_shopping_list(shopping_list, copy_button)
        copy_button.pack(side="right")

        for item in shopping_list:
            self.add_shopping_item(card, item)
        return card

    def add_shopping_item(self, card, item):
        label = tk.Label(card, text=f"☐   {item}", font=BODY_FONT, fg=TEXT_MAIN,
                         bg="#FFFFFF", anchor="w", cursor="hand2", pady=3)
        label.pack(fill="x")
        label.ticked = False

        def toggle(_event=None):
            label.ticked = not label.ticked
            if label.ticked:
                label.config(text=f"☑   {item}", fg=TEXT_MUTED,
                             font=(BODY_FONT[0], BODY_FONT[1], "overstrike"))
            else:
                label.config(text=f"☐   {item}", fg=TEXT_MAIN, font=BODY_FONT)

        label.bind("<Button-1>", toggle)

    def copy_shopping_list(self, shopping_list, button):
        lines = []
        for item in shopping_list:
            lines.append(f"- {item}")
        self.root.clipboard_clear()
        self.root.clipboard_append("Shopping list\n" + "\n".join(lines))
        button.config(text="Copied ✓")
        self.root.after(2000, lambda: button.winfo_exists() and button.config(text="Copy list"))

    # ------------------------------------------------------------------
    # Running the agent (worker thread)
    # The worker never touches widgets; it only puts events on self.events.
    # ------------------------------------------------------------------

    def start_session(self):
        if self.session_running:
            return
        if self.chat.inner.winfo_children():
            self.add_note("─────────   New meal plan   ─────────")
        self.session_running = True
        self.waiting_for_user = False
        self.replies_this_session = 0
        self.user_replies = queue.Queue()
        # The old plan's highlights no longer apply.
        self.pantry_items_in_plan = set()
        self.refresh_pantry_list()
        self.update_controls()
        self.start_thinking_animation("Starting")
        threading.Thread(target=self.run_agent_session, daemon=True).start()

    def agent_input(self, _prompt):
        """input_fn for the agent: wait until the user sends a message."""
        self.events.put(("waiting_for_user", None))
        return self.user_replies.get()

    def agent_output(self, text):
        """output_fn for the agent: show its message in the chat."""
        self.events.put(("agent_output", text))

    def run_agent_session(self):
        """Same steps as main.py, with the chat window instead of the terminal."""
        try:
            if self.agent is None:
                self.events.put(("status", "Loading model"))
                from agent import Agent

                config.validate()
                self.agent = Agent(config.MODEL_PATH)

            self.events.put(("status", "Thinking"))
            meal_plan = self.agent.generate_meal_plan(
                input_fn=self.agent_input, output_fn=self.agent_output
            )
            if meal_plan:
                self.events.put(("status", "Building shopping list"))
                pantry_list = self.agent.search_pantry()

                # What to buy for each meal, using the agent's own pantry filter.
                to_buy_per_meal = []
                for meal in meal_plan:
                    to_buy_per_meal.append(
                        self.agent.generate_shopping_list([meal], pantry_list)
                    )
                self.events.put(("meal_plan", (meal_plan, to_buy_per_meal, pantry_list)))

                # The full list, as main.py prints it (duplicates across meals removed).
                shopping_list = self.agent.generate_shopping_list(meal_plan, pantry_list)
                self.events.put(("shopping_list", shopping_list))
        except Exception as error:
            self.events.put(("error", f"Details: {error}"))
        finally:
            self.events.put(("session_done", None))


def run_gui():
    root = tk.Tk()
    GroceryAgentChatGUI(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
