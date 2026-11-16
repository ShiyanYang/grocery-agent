"""Chat window for the grocery agent.

The window runs the same steps as main.py:
    1. agent.generate_meal_plan()      - the chat with the user
    2. agent.generate_shopping_list()  - what to buy, after removing pantry items

agent.py is not changed. generate_meal_plan() takes an input_fn and an output_fn, so the
GUI passes its own versions: input_fn waits for the user to type in the chat box, and
output_fn shows the agent's messages in the chat box. The agent runs on a worker thread
so the window stays responsive while the model is working.
"""
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk

from config import config
from pantry import load_pantry, save_pantry

# Colors used across the window.
BG_WINDOW = "#000000"
BG_CARD = "#111111"
BG_INPUT = "#000000"
BORDER = "#2a2a2a"
TEXT_MAIN = "#ffffff"
TEXT_MUTED = "#9ca3af"
USER_COLOR = "#60a5fa"
ASSISTANT_COLOR = "#34d399"
STATUS_COLOR = "#fbbf24"

# Who is speaking: (emoji, display name, color).
SPEAKERS = {
    "user": ("🧑", "You", USER_COLOR),
    "assistant": ("🛒", "Grocery Agent", ASSISTANT_COLOR),
    "status": ("⚙️", "Agent status", STATUS_COLOR),
}

# The agent prefixes model replies with this (see Agent._ask).
ANSWER_PREFIX = "Answer:"

# Agent messages that report on its own progress rather than talk to the user.
STATUS_PREFIXES = (
    "Meal plan rejected",
    "Meal plan generated",
    "Could not get a valid meal plan",
    "MLX model generation is not available",
)

# A model reply that contains a meal plan: a JSON list of objects (same check as
# Agent._check_meal_plan). The plan itself is shown as a table, not as JSON.
PLAN_START = re.compile(r"\[\s*\{")

# Meal plan table: (column title, wrap width in pixels).
TABLE_COLUMNS = [
    ("Day", 70),
    ("Meal", 80),
    ("Dish", 150),
    ("Ingredients", 220),
    ("To buy", 180),
]
TABLE_HEADER_BG = "#1f2937"
TABLE_ROW_BGS = ["#0b0b0b", "#161616"]

# Frames for the "thinking" animation shown in the chat box.
THINKING_FRAMES = ["🥕", "🥦", "🍅", "🧀", "🍞", "🥚"]
THINKING_DOTS = ["   ", ".  ", ".. ", "..."]
ANIMATION_DELAY_MS = 150
EVENT_POLL_MS = 100


class GroceryAgentChatGUI:
    """Chat window with an editable pantry panel on the side."""

    def __init__(self, root):
        self.root = root
        self.root.title("Grocery Agent")
        self.root.geometry("1200x820")
        self.root.configure(bg=BG_WINDOW)

        self.agent = None
        # Worker thread -> UI: (event_name, data) tuples. See handle_event().
        self.events = queue.Queue()
        # UI -> worker thread: what the user typed, read by the agent's input_fn.
        self.user_replies = queue.Queue()

        self.session_running = False
        self.waiting_for_user = False
        self.animation_running = False
        self.animation_label = "Thinking"
        self.animation_step = 0
        self.animation_timer = None

        self.build_ui()
        self.refresh_pantry_list()
        self.poll_events()
        self.start_session()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def build_ui(self):
        outer = tk.Frame(self.root, bg=BG_WINDOW)
        outer.pack(fill="both", expand=True, padx=22, pady=22)

        # Pantry panel on the left, chat fills the rest on the right.
        pantry_card = self.make_card(outer)
        pantry_card.pack(side="left", fill="y", padx=(0, 16))
        self.build_pantry_panel(pantry_card)

        chat_card = self.make_card(outer)
        chat_card.pack(side="right", fill="both", expand=True)
        self.build_chat_panel(chat_card)

    def make_card(self, parent):
        return tk.Frame(
            parent,
            bg=BG_CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=18,
            pady=18,
        )

    def build_chat_panel(self, card):
        topbar = tk.Frame(card, bg=BG_CARD)
        topbar.pack(fill="x", pady=(0, 14))

        title_block = tk.Frame(topbar, bg=BG_CARD)
        title_block.pack(side="left")
        tk.Label(
            title_block,
            text="Grocery Agent",
            font=("Arial", 20, "bold"),
            fg=TEXT_MAIN,
            bg=BG_CARD,
        ).pack(anchor="w")
        tk.Label(
            title_block,
            text="Meal planning and pantry assistant",
            font=("Arial", 10),
            fg=TEXT_MUTED,
            bg=BG_CARD,
        ).pack(anchor="w", pady=(4, 0))

        self.new_plan_button = self.make_button(topbar, "New plan", self.start_session)
        self.new_plan_button.pack(side="right")

        # Input row is packed before the chat box so it always stays visible.
        input_frame = tk.Frame(card, bg=BG_CARD)
        input_frame.pack(side="bottom", fill="x", pady=(18, 0))

        self.user_input = tk.Entry(
            input_frame,
            font=("Arial", 12),
            relief="flat",
            bg=BG_INPUT,
            fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN,
            highlightbackground="#3a3a3a",
            highlightthickness=1,
        )
        self.user_input.pack(side="left", fill="x", expand=True, ipady=12)
        self.user_input.bind("<Return>", self.on_submit)

        self.send_button = self.make_button(input_frame, "Send", self.send_message)
        self.send_button.pack(side="right", padx=(10, 0))

        chat_frame = tk.Frame(card, bg=BG_INPUT)
        chat_frame.pack(fill="both", expand=True)

        self.chat_box = tk.Text(
            chat_frame,
            wrap="word",
            bg=BG_INPUT,
            fg=TEXT_MAIN,
            relief="flat",
            font=("Arial", 12),
            padx=12,
            pady=12,
            state="disabled",
        )
        scrollbar = ttk.Scrollbar(chat_frame, orient="vertical", command=self.chat_box.yview)
        scrollbar.pack(side="right", fill="y")
        self.chat_box.pack(side="left", fill="both", expand=True)
        self.chat_box.config(yscrollcommand=scrollbar.set)

        # Text styles for each speaker.
        for sender, (_, _, color) in SPEAKERS.items():
            self.chat_box.tag_config(
                f"{sender}_name", foreground=color, font=("Arial", 12, "bold")
            )
            self.chat_box.tag_config(
                f"{sender}_text", lmargin1=28, lmargin2=28, spacing3=14
            )
        self.chat_box.tag_config("status_text", foreground=TEXT_MUTED, font=("Arial", 11))
        self.chat_box.tag_config("thinking", foreground=TEXT_MUTED, font=("Arial", 12, "italic"))

    def build_pantry_panel(self, card):
        tk.Label(
            card,
            text="🧺 Pantry",
            font=("Arial", 16, "bold"),
            fg=TEXT_MAIN,
            bg=BG_CARD,
        ).pack(anchor="w")

        tk.Label(
            card,
            text="Select an item to edit or remove it.",
            font=("Arial", 10),
            fg=TEXT_MUTED,
            bg=BG_CARD,
        ).pack(anchor="w", pady=(4, 10))

        self.pantry_listbox = tk.Listbox(
            card,
            width=28,
            bg=BG_INPUT,
            fg=TEXT_MAIN,
            selectbackground="#374151",
            selectforeground=TEXT_MAIN,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#3a3a3a",
            font=("Arial", 12),
            activestyle="none",
            exportselection=False,
        )
        self.pantry_listbox.pack(fill="both", expand=True)
        self.pantry_listbox.bind("<<ListboxSelect>>", self.on_pantry_select)

        self.pantry_entry = tk.Entry(
            card,
            font=("Arial", 12),
            relief="flat",
            bg=BG_INPUT,
            fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN,
            highlightbackground="#3a3a3a",
            highlightthickness=1,
        )
        self.pantry_entry.pack(fill="x", pady=(12, 8), ipady=8)
        self.pantry_entry.bind("<Return>", lambda _event: self.add_pantry_item())

        button_row = tk.Frame(card, bg=BG_CARD)
        button_row.pack(fill="x")
        self.make_button(button_row, "Add", self.add_pantry_item).pack(
            side="left", expand=True, fill="x"
        )
        self.make_button(button_row, "Update", self.update_pantry_item).pack(
            side="left", expand=True, fill="x", padx=6
        )
        self.make_button(button_row, "Remove", self.remove_pantry_item).pack(
            side="left", expand=True, fill="x"
        )

        self.pantry_status = tk.Label(
            card, text="", font=("Arial", 10), fg=TEXT_MUTED, bg=BG_CARD, anchor="w"
        )
        self.pantry_status.pack(fill="x", pady=(8, 0))

    def make_button(self, parent, text, command):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=TEXT_MAIN,
            fg=BG_WINDOW,
            font=("Arial", 11, "bold"),
            relief="flat",
            padx=12,
            pady=8,
            cursor="hand2",
        )

    # ------------------------------------------------------------------
    # Pantry editing
    # The agent reads data/pantry.json when it builds the shopping list,
    # so edits made here are used by the next shopping list.
    # ------------------------------------------------------------------

    def refresh_pantry_list(self):
        self.pantry_listbox.delete(0, "end")
        for item in load_pantry():
            self.pantry_listbox.insert("end", item)

    def selected_pantry_index(self):
        selection = self.pantry_listbox.curselection()
        if not selection:
            return None
        return selection[0]

    def on_pantry_select(self, _event=None):
        index = self.selected_pantry_index()
        if index is None:
            return
        self.pantry_entry.delete(0, "end")
        self.pantry_entry.insert(0, self.pantry_listbox.get(index))

    def save_pantry_items(self, items, status_text):
        try:
            save_pantry(items)
        except Exception as error:
            self.pantry_status.config(text=f"Could not save: {error}")
            return
        self.refresh_pantry_list()
        self.pantry_entry.delete(0, "end")
        self.pantry_status.config(text=status_text)

    def add_pantry_item(self):
        new_item = self.pantry_entry.get().strip()
        if not new_item:
            self.pantry_status.config(text="Type an item name first.")
            return
        items = load_pantry()
        if new_item in items:
            self.pantry_status.config(text=f"'{new_item}' is already in the pantry.")
            return
        items.append(new_item)
        self.save_pantry_items(items, f"Added '{new_item}'.")

    def update_pantry_item(self):
        index = self.selected_pantry_index()
        new_name = self.pantry_entry.get().strip()
        if index is None or not new_name:
            self.pantry_status.config(text="Select an item and type its new name.")
            return
        items = load_pantry()
        old_name = items[index]
        items[index] = new_name
        self.save_pantry_items(items, f"Renamed '{old_name}' to '{new_name}'.")

    def remove_pantry_item(self):
        index = self.selected_pantry_index()
        if index is None:
            self.pantry_status.config(text="Select an item to remove.")
            return
        items = load_pantry()
        removed = items.pop(index)
        self.save_pantry_items(items, f"Removed '{removed}'.")

    # ------------------------------------------------------------------
    # Chat display
    # ------------------------------------------------------------------

    def add_message(self, sender, text, widget=None):
        """Add a message to the chat. widget, if given, is shown below the text."""
        emoji, name, _ = SPEAKERS[sender]
        # Keep the thinking animation as the last line of the chat.
        was_animating = self.animation_running
        if was_animating:
            self.stop_thinking_animation()

        self.chat_box.config(state="normal")
        self.chat_box.insert("end", f"{emoji}  {name}\n", f"{sender}_name")
        self.chat_box.insert("end", f"{text}\n", f"{sender}_text")
        if widget is not None:
            self.chat_box.window_create("end", window=widget, padx=28)
            self.chat_box.insert("end", "\n\n")
        self.chat_box.see("end")
        self.chat_box.config(state="disabled")

        if was_animating:
            self.start_thinking_animation(self.animation_label)

    def start_thinking_animation(self, label="Thinking"):
        self.animation_label = label
        if self.animation_running:
            return
        self.animation_running = True
        self.chat_box.config(state="normal")
        # Remember where the animation line starts so we can redraw or delete it.
        self.chat_box.mark_set("thinking_start", "end-1c")
        self.chat_box.mark_gravity("thinking_start", "left")
        self.chat_box.config(state="disabled")
        self.animate()

    def stop_thinking_animation(self):
        if not self.animation_running:
            return
        self.animation_running = False
        if self.animation_timer is not None:
            self.root.after_cancel(self.animation_timer)
            self.animation_timer = None
        self.chat_box.config(state="normal")
        self.chat_box.delete("thinking_start", "end-1c")
        self.chat_box.config(state="disabled")

    def animate(self):
        if not self.animation_running:
            return
        food = THINKING_FRAMES[(self.animation_step // 2) % len(THINKING_FRAMES)]
        dots = THINKING_DOTS[self.animation_step % len(THINKING_DOTS)]
        self.chat_box.config(state="normal")
        self.chat_box.delete("thinking_start", "end-1c")
        self.chat_box.insert("thinking_start", f"{food}  {self.animation_label}{dots}\n", "thinking")
        self.chat_box.see("end")
        self.chat_box.config(state="disabled")
        self.animation_step += 1
        self.animation_timer = self.root.after(ANIMATION_DELAY_MS, self.animate)

    def update_controls(self):
        """Enable the input only while the agent is waiting for the user."""
        if self.waiting_for_user:
            self.send_button.config(state="normal")
            self.user_input.config(state="normal")
            self.user_input.focus_set()
        else:
            self.send_button.config(state="disabled")
            self.user_input.config(state="disabled")

        if self.session_running:
            self.new_plan_button.config(state="disabled")
        else:
            self.new_plan_button.config(state="normal")

    # ------------------------------------------------------------------
    # Talking to the user (called by the UI thread)
    # ------------------------------------------------------------------

    def send_message(self):
        if not self.waiting_for_user:
            return
        text = self.user_input.get().strip()
        if not text:
            return

        self.add_message("user", text)
        self.user_input.delete(0, "end")
        self.waiting_for_user = False
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
            meal_plan, to_buy_per_meal = data
            self.show_meal_plan(meal_plan, to_buy_per_meal)
        elif event_name == "shopping_list":
            self.show_shopping_list(data)
        elif event_name == "error":
            self.add_message("status", data)
        elif event_name == "session_done":
            self.stop_thinking_animation()
            self.session_running = False
            self.waiting_for_user = False
            self.update_controls()
            self.add_message("status", "Session finished. Press 'New plan' to start again.")

    def show_agent_output(self, text):
        if text.startswith(ANSWER_PREFIX):
            answer = text[len(ANSWER_PREFIX):].strip()
            plan_start = PLAN_START.search(answer)
            if plan_start is None:
                self.add_message("assistant", answer)
                return
            # Hide the JSON. If the plan is valid it is shown as a table once the
            # agent accepts it; if not, the agent's rejection message explains why.
            text_before_plan = answer[:plan_start.start()].strip()
            message = "📝 I drafted a meal plan."
            if text_before_plan:
                message = f"{text_before_plan}\n{message}"
            self.add_message("assistant", message)
        elif text.startswith(STATUS_PREFIXES):
            self.add_message("status", text)
        else:
            self.add_message("assistant", text)

    def show_meal_plan(self, meal_plan, to_buy_per_meal):
        table = self.build_meal_table(meal_plan, to_buy_per_meal)
        self.add_message("assistant", "🍽️ Here is your meal plan:", widget=table)

    def build_meal_table(self, meal_plan, to_buy_per_meal):
        """A grid of labels, one row per meal. The thin gaps between cells form the grid lines."""
        table = tk.Frame(self.chat_box, bg=BORDER)

        for column, (title, width) in enumerate(TABLE_COLUMNS):
            # Fixed column widths so every row lines up; the 16 covers the cell padding.
            table.grid_columnconfigure(column, minsize=width + 16)
            self.make_table_cell(table, title, width, TABLE_HEADER_BG, bold=True).grid(
                row=0, column=column, sticky="nsew", padx=(0, 1), pady=(0, 1)
            )

        for index, meal in enumerate(meal_plan):
            row_bg = TABLE_ROW_BGS[index % len(TABLE_ROW_BGS)]
            to_buy = to_buy_per_meal[index]
            if to_buy:
                to_buy_text = "\n".join(f"• {item}" for item in to_buy)
                to_buy_color = TEXT_MAIN
            else:
                to_buy_text = "✓ All in pantry"
                to_buy_color = ASSISTANT_COLOR

            cells = [
                (meal.get("day", ""), TEXT_MAIN),
                (str(meal.get("meal_type", "")).capitalize(), TEXT_MAIN),
                (meal.get("meal_name", ""), TEXT_MAIN),
                (", ".join(meal.get("ingredients", [])), TEXT_MUTED),
                (to_buy_text, to_buy_color),
            ]
            for column, (text, color) in enumerate(cells):
                width = TABLE_COLUMNS[column][1]
                cell = self.make_table_cell(table, text, width, row_bg, color=color)
                cell.grid(row=index + 1, column=column, sticky="nsew", padx=(0, 1), pady=(0, 1))

        return table

    def make_table_cell(self, parent, text, width, bg, color=TEXT_MAIN, bold=False):
        weight = "bold" if bold else "normal"
        return tk.Label(
            parent,
            text=text,
            bg=bg,
            fg=color,
            font=("Arial", 11, weight),
            wraplength=width,
            width=0,
            justify="left",
            anchor="nw",
            padx=8,
            pady=6,
        )

    def show_shopping_list(self, shopping_list):
        if not shopping_list:
            self.add_message("assistant", "🧾 Everything you need is already in your pantry.")
            return
        lines = ["🧾 The shopping list is:"]
        for item in shopping_list:
            lines.append(f"  - {item}")
        self.add_message("assistant", "\n".join(lines))

    # ------------------------------------------------------------------
    # Running the agent (worker thread)
    # The worker never touches widgets; it only puts events on self.events.
    # ------------------------------------------------------------------

    def start_session(self):
        if self.session_running:
            return
        self.session_running = True
        self.waiting_for_user = False
        self.user_replies = queue.Queue()
        self.update_controls()
        self.start_thinking_animation("Starting")
        threading.Thread(target=self.run_agent_session, daemon=True).start()

    def agent_input(self, _prompt):
        """input_fn for the agent: wait until the user sends a message."""
        self.events.put(("waiting_for_user", None))
        return self.user_replies.get()

    def agent_output(self, text):
        """output_fn for the agent: show its message in the chat box."""
        self.events.put(("agent_output", text))

    def run_agent_session(self):
        """Same steps as main.py, with the chat box instead of the terminal."""
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
                self.events.put(("meal_plan", (meal_plan, to_buy_per_meal)))

                # The full list, as main.py prints it (duplicates across meals removed).
                shopping_list = self.agent.generate_shopping_list(meal_plan, pantry_list)
                self.events.put(("shopping_list", shopping_list))
        except Exception as error:
            self.events.put(("error", f"Something went wrong: {error}"))
        finally:
            self.events.put(("session_done", None))


def run_gui():
    root = tk.Tk()
    GroceryAgentChatGUI(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
