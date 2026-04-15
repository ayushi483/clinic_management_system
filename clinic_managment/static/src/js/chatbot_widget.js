/** @odoo-module **/
/**
 * Clinic Chatbot — OWL Component
 * File: clinic_managment/static/src/js/chatbot_component.js
 */

import { Component, useState, useRef, onMounted, onPatched, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";

const WELCOME_TEXT = "👋 Hello! I'm your Clinic Assistant.\n\nI can help you:\n📅 Book an appointment\n📋 View patient or doctor records\n🕐 Check doctor availability\n\nTry: \"Book patient 5 with Dr. Ahmed tomorrow at 10 AM\"";

class ClinicChatbot extends Component {
    static template = "clinic_managment.ClinicChatbot";
    static props = {};

    setup() {
        this.state = useState({
            open: false,
            message: "",
            messages: [{ role: "assistant", text: WELCOME_TEXT }],
            loading: false,
            listening: false,
        });

        this.history = [];
        this.messagesRef = useRef("messages");
        this.recognition = null;

        // ── Voice INPUT only (no TTS output) ────────────────
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            this.recognition = new SpeechRecognition();
            this.recognition.continuous = false;
            this.recognition.interimResults = false;
            this.recognition.lang = "en-US";

            this.recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                this.state.message = transcript;
                this.state.listening = false;
                this.sendMessage();
            };
            this.recognition.onerror = () => { this.state.listening = false; };
            this.recognition.onend   = () => { this.state.listening = false; };
        }

        onMounted(() => this._scrollToBottom());
        onPatched(() => this._scrollToBottom());
    }

    // ── Panel toggle ─────────────────────────────
    toggleChat() {
        this.state.open = !this.state.open;
    }

    // ── Clear / reset conversation ───────────────
    clearChat() {
        this.history = [];
        this.state.messages = [{ role: "assistant", text: WELCOME_TEXT }];
    }

    // ── Input handlers ───────────────────────────
    onInputChange(ev) {
        this.state.message = ev.target.value;
    }

    onInputKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    // ── Voice input ──────────────────────────────
    toggleVoice() {
        if (!this.recognition) return;
        if (this.state.listening) {
            this.recognition.stop();
            this.state.listening = false;
        } else {
            this.recognition.start();
            this.state.listening = true;
        }
    }

    // ── Quick chip shortcut ──────────────────────
    sendQuickAction(ev) {
        const action = ev.currentTarget.dataset.action;
        this.state.message = action;
        this.sendMessage();
    }

    // ── Main send ────────────────────────────────
    async sendMessage() {
        const text = this.state.message.trim();
        if (!text || this.state.loading) return;

        this.state.messages = [...this.state.messages, { role: "user", text }];
        this.history.push({ role: "user", content: text });
        this.state.message = "";
        this.state.loading = true;

        try {
            // Get the browser's UTC offset in minutes so the server can
            // correctly interpret "tomorrow at 10 AM" in the user's local time.
            const tzOffset = new Date().getTimezoneOffset(); // minutes behind UTC (negative = ahead)
            const tzName = Intl.DateTimeFormat().resolvedOptions().timeZone;

            const response = await fetch("/api/v19/chatbot/message", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    history: this.history.slice(-12),
                    tz_offset: tzOffset,      // e.g. -330 for IST
                    tz_name: tzName,          // e.g. "Asia/Kolkata"
                }),
            });

            if (!response.ok) throw new Error("HTTP " + response.status);

            const data = await response.json();
            const reply = data?.data?.reply || "Sorry, I could not process that.";

            this.state.messages = [...this.state.messages, { role: "assistant", text: reply }];
            this.history.push({ role: "assistant", content: reply });

        } catch (err) {
            this.state.messages = [...this.state.messages, {
                role: "assistant",
                text: "⚠️ Connection error. Please try again.",
            }];
        } finally {
            this.state.loading = false;
        }
    }

    // ── Helpers ──────────────────────────────────
    _scrollToBottom() {
        const el = this.messagesRef.el;
        if (el) el.scrollTop = el.scrollHeight;
    }

    /**
     * Escapes HTML then applies minimal markup.
     * Returns an OWL markup() object so t-out renders it as real HTML.
     * Without markup(), OWL's t-out escapes the string and <br> shows as literal text.
     */
    formatText(raw) {
        const html = raw
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
            .replace(/\n/g, "<br>");
        // markup() tells OWL this string is safe to render as HTML
        return markup(html);
    }
}

// ── Register in systray ───────────────────────────────────
registry.category("systray").add("clinic_chatbot", {
    Component: ClinicChatbot,
}, { sequence: 1 });

export { ClinicChatbot };