/** @odoo-module **/
import { Component, useState, useRef, onMounted, onPatched, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const WELCOME_TEXT = [
    "Hello! I'm your Clinic Assistant 👋\n\n",
    "Use the menu below or just type freely.\n\n",
    "**Quick actions:**\n",
    "• Book an appointment\n",
    "• View patient records\n",
    "• Check doctor availability\n",
    "• Open any record directly\n\n",
    "**Navigation examples:**\n",
    "• \"show appointments\"\n",
    "• \"open patient PAT001\"\n",
    "• \"open appointment APP0039\"\n",
    "• \"open doctor Ayush\"",
].join("");

const PAGE_ROUTES = {
    appointments:  { model: "clinic.appointment",  view_mode: "list,form", name: "Appointments" },
    patients:      { model: "clinic.patient",       view_mode: "list,form", name: "Patients" },
    doctors:       { model: "clinic.doctor",        view_mode: "list,form", name: "Doctors" },
    consultations: { model: "clinic.consultation",  view_mode: "list,form", name: "Consultations" },
};

const VIEWS = {
    CHAT: "chat", MENU: "menu",
    BOOK_DOCTOR: "book_doctor", BOOK_DATE: "book_date",
    BOOK_TIME: "book_time", BOOK_PATIENT: "book_patient",
    BOOK_NOTES: "book_notes", BOOK_CONFIRM: "book_confirm",
    RECORDS_TYPE: "records_type", AVAIL_DOCTOR: "avail_doctor",
    AVAIL_DATE: "avail_date", NAV: "nav", OPEN_TYPE: "open_type",
};

const SpeechRecognitionClass =
    window.SpeechRecognition || window.webkitSpeechRecognition || null;

// ══════════════════════════════════════════════════════════════════════════════
// MEMORY SYSTEM — localStorage, zero leaks
//
// Anti-leak rules:
//  1. Max 60 messages per patient (oldest trimmed on every save)
//  2. Max 50 patients total in localStorage (LRU eviction via meta index)
//  3. Messages older than 90 days are pruned automatically on load
//  4. _fromMemory-tagged messages are NEVER written back to storage
//  5. Only role=user / role=assistant messages are stored (no UI dividers)
// ══════════════════════════════════════════════════════════════════════════════

const MEM_PREFIX    = "clinic_chat:";
const MEM_META_KEY  = "clinic_chat_meta";
const MAX_MSGS      = 60;
const MAX_PATIENTS  = 50;
const EXPIRY_MS     = 90 * 24 * 60 * 60 * 1000; // 90 days

function _norm(code) {
    return String(code).replace(/[\s\-/]/g, "").toUpperCase();
}
function _patKey(code) { return MEM_PREFIX + _norm(code); }

function _metaLoad() {
    try { return JSON.parse(localStorage.getItem(MEM_META_KEY) || "{}"); }
    catch { return {}; }
}
function _metaSave(meta) {
    try { localStorage.setItem(MEM_META_KEY, JSON.stringify(meta)); } catch {}
}
function _metaTouch(code) {
    const meta = _metaLoad();
    meta[_norm(code)] = Date.now();
    const keys = Object.keys(meta);
    if (keys.length > MAX_PATIENTS) {
        const lru = keys.sort((a, b) => meta[a] - meta[b])[0];
        try { localStorage.removeItem(_patKey(lru)); } catch {}
        delete meta[lru];
    }
    _metaSave(meta);
}
function _metaRemove(code) {
    const meta = _metaLoad();
    delete meta[_norm(code)];
    _metaSave(meta);
}

/** Load stored messages for a patient. Returns [] if none or expired. */
function memLoad(patientCode) {
    try {
        const raw = localStorage.getItem(_patKey(patientCode));
        if (!raw) return [];
        const msgs   = JSON.parse(raw);
        const cutoff = Date.now() - EXPIRY_MS;
        return msgs.filter(m => (m.timestamp || 0) >= cutoff);
    } catch { return []; }
}

/**
 * Persist messages for a patient.
 * Only real user/assistant turns are written.
 * _fromMemory-tagged messages are excluded.
 */
function memSave(patientCode, visibleMessages) {
    if (!patientCode) return;
    try {
        const toSave = visibleMessages
            .filter(m =>
                (m.role === "user" || m.role === "assistant") &&
                !m._fromMemory
            )
            .slice(-MAX_MSGS)
            .map(m => ({
                role:      m.role,
                text:      m.text,
                timestamp: m.timestamp || Date.now(),
            }));
        localStorage.setItem(_patKey(patientCode), JSON.stringify(toSave));
        _metaTouch(patientCode);
    } catch (e) { console.warn("[Memory] Save failed:", e); }
}

/** Remove a patient's memory from localStorage entirely. */
function memDelete(patientCode) {
    try {
        localStorage.removeItem(_patKey(patientCode));
        _metaRemove(patientCode);
    } catch (e) { console.warn("[Memory] Delete failed:", e); }
}

function extractPatCode(text) {
    const m = String(text).match(/\b(PAT[\s\-/]*\d{1,6})\b/i);
    return m ? _norm(m[1]) : null;
}

function getDateChips() {
    const chips = [], now = new Date();
    const days   = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
    const months = ["Jan","Feb","Mar","Apr","May","Jun",
                    "Jul","Aug","Sep","Oct","Nov","Dec"];
    for (let i = 0; i < 10; i++) {
        const d = new Date(now);
        d.setDate(now.getDate() + i);
        chips.push({
            label: i === 0 ? "Today" : i === 1 ? "Tmrw" : days[d.getDay()],
            num:   d.getDate(),
            month: months[d.getMonth()],
            value: d.toISOString().slice(0, 10),
        });
    }
    return chips;
}

function getTimeSlots() {
    const slots = { morning: [], afternoon: [], evening: [] };
    for (let h = 8; h < 20; h++) {
        for (let m = 0; m < 60; m += 30) {
            const label = `${h % 12 || 12}:${m === 0 ? "00" : "30"} ${h < 12 ? "AM" : "PM"}`;
            const value = `${String(h).padStart(2,"0")}:${m === 0 ? "00" : "30"}`;
            const slot  = { label, value };
            if      (h < 12) slots.morning.push(slot);
            else if (h < 17) slots.afternoon.push(slot);
            else             slots.evening.push(slot);
        }
    }
    return slots;
}

function normCode(s) { return String(s).replace(/[\\/\-\s]/g, "").toUpperCase(); }

// ══════════════════════════════════════════════════════════════════════════════
// COMPONENT
// ══════════════════════════════════════════════════════════════════════════════

class ClinicChatbot extends Component {
    static template = "clinic_managment.ClinicChatbot";
    static props    = {};

    setup() {
        this.state = useState({
            open: false, view: VIEWS.MENU, message: "", loading: false, listening: false,
            messages: [{ role: "assistant", text: WELCOME_TEXT, timestamp: Date.now() }],
            doctors: [], doctorsLoading: false,
            booking: {
                doctor: null, date: "", dateLabel: "",
                time: "", timeLabel: "", patientCode: "", notes: "",
            },
            bookedSlots: [], slotsLoading: false,
            recordsType: "patient", recordsInput: "",
            availDoctor: null, availDate: "",
            openType: "patient", openInput: "",
            breadcrumbs: [],
            streamingText: "",
            isStreaming:   false,
            // memory UI
            activePatientCode: null,
            memoryLoaded:      false,
            memoryCount:       0,
        });

        this.action      = useService("action");
        this.history     = [];
        this.dateChips   = getDateChips();
        this.timeSlots   = getTimeSlots();
        this.messagesRef = useRef("messages");
        this.currentRec  = null;
        // Track which patient codes we've already shown memory for in this session
        this._shownMemoryFor = new Set();

        onMounted(() => { this._scrollToBottom(); this._loadDoctors(); });
        onPatched(() => this._scrollToBottom());
    }

    get tz() { return Intl.DateTimeFormat().resolvedOptions().timeZone; }

    get safeBookingDoctor() {
        return this.state.booking.doctor ||
               { name: "", speciality: "", fees: "0", is_available: false };
    }

    async _post(url, body) {
        const res = await fetch(url, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    async _loadDoctors() {
        this.state.doctorsLoading = true;
        try {
            const data = await this._post("/api/v19/chatbot/doctors", {});
            this.state.doctors = data.result?.doctors ?? data.doctors ?? [];
        } catch (e) {
            console.error("loadDoctors:", e);
            this.state.doctors = [];
        } finally {
            this.state.doctorsLoading = false;
        }
    }

    async _loadBookedSlots() {
        if (!this.state.booking.doctor || !this.state.booking.date) return;
        this.state.slotsLoading = true;
        try {
            const data = await this._post("/api/v19/chatbot/booked_slots", {
                doctor_id: this.state.booking.doctor.id,
                date:      this.state.booking.date,
                tz_name:   this.tz,
            });
            this.state.bookedSlots = data.booked ?? [];
        } catch (e) {
            this.state.bookedSlots = [];
        } finally {
            this.state.slotsLoading = false;
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // MEMORY METHODS
    // ══════════════════════════════════════════════════════════════════════════

    /**
     * Activate memory for a patient.
     *
     * KEY FIX: We track which patients have had memory shown via _shownMemoryFor.
     * - First time a patient code appears → load & show history, inject into Ollama context
     * - Subsequent times (e.g. re-booking same patient) → silently update activePatientCode
     *   so saves go to the right bucket, but DON'T re-inject the history popup
     *
     * This means: after a booking, if you re-book the same patient, the history is
     * already in this.history (injected the first time), and we don't duplicate it.
     * But if you clear chat and come back, _shownMemoryFor is reset so history shows again.
     */
    _activatePatientMemory(patientCode) {
        const code = _norm(patientCode);
        if (!code) return;

        // Save previous patient before switching to a different one
        if (this.state.activePatientCode && this.state.activePatientCode !== code) {
            this._saveCurrentMemory();
            // Remove old patient's memory entries from Ollama history
            this.history = this.history.filter(m => !m._fromMemory);
        }

        this.state.activePatientCode = code;

        // If we've already shown memory for this patient in this session, skip the UI injection
        // but still keep the activePatientCode set (for saves)
        if (this._shownMemoryFor.has(code)) {
            return;
        }

        // Mark as shown so we don't show again during this chat session
        this._shownMemoryFor.add(code);

        const past = memLoad(code);

        this.state.memoryLoaded = past.length > 0;
        this.state.memoryCount  = past.length;

        if (past.length > 0) {
            // ── 1. Visible chat: divider ─────────────────────────────────────
            this.state.messages = [
                ...this.state.messages,
                {
                    role:      "system-memory",
                    text:      `🧠 Memory loaded for **${code}** — ${past.length} message(s) from past session(s).`,
                    timestamp: Date.now(),
                },
            ];

            // ── 2. Visible chat: summary bubble ─────────────────────────────
            const recentUserMsgs = past.filter(m => m.role === "user").slice(-5);
            const lastDate = past[past.length - 1]?.timestamp
                ? new Date(past[past.length - 1].timestamp).toLocaleDateString("en-IN", {
                    day: "numeric", month: "short", year: "numeric",
                  })
                : "a previous session";
            const snippets = recentUserMsgs
                .map(m => `• "${m.text.slice(0, 70)}${m.text.length > 70 ? "…" : ""}"`)
                .join("\n");

            this.state.messages = [
                ...this.state.messages,
                {
                    role:        "assistant",
                    text:        `📂 **Past session recalled for ${code}**\n\n`
                                 + `Last seen: **${lastDate}**\n\n`
                                 + (snippets ? `**Recent queries:**\n${snippets}\n\n` : "")
                                 + `How can I help you today?`,
                    timestamp:   Date.now(),
                    _fromMemory: true,
                },
            ];

            // ── 3. Inject into Ollama history ─────────────────────────────────
            this.history = this.history.filter(m => !m._fromMemory);

            const injected = past.slice(-20).map(m => ({
                role:        m.role,
                content:     m.text,
                _fromMemory: true,
            }));

            this.history = [
                {
                    role:        "system",
                    content:     `[MEMORY] Previous conversation with patient ${code}:\n`
                                 + injected.map(m => `${m.role}: ${m.content}`).join("\n"),
                    _fromMemory: true,
                },
                ...injected,
                ...this.history,
            ];
        }
    }

    /** Write current session messages to localStorage for the active patient. */
    _saveCurrentMemory() {
        if (!this.state.activePatientCode) return;
        memSave(this.state.activePatientCode, this.state.messages);
    }

    /** Delete memory for the active patient and clean up UI + history. */
    clearPatientMemory() {
        if (!this.state.activePatientCode) return;
        const code = this.state.activePatientCode;
        memDelete(code);

        // Also remove from shown-set so if patient is re-typed, fresh load happens
        this._shownMemoryFor.delete(code);

        this.state.messages = this.state.messages.filter(
            m => m.role !== "system-memory" && !m._fromMemory
        );
        this.history = this.history.filter(m => !m._fromMemory);

        this.state.memoryLoaded = false;
        this.state.memoryCount  = 0;
        this._pushAssistant(`🗑️ Memory cleared for patient **${code}**.`);
    }

    /**
     * Detect patient code in any text and activate their memory.
     * Safe to call on every message — guard inside _activatePatientMemory handles dedup.
     */
    _checkAndActivateMemory(text) {
        const code = extractPatCode(text);
        if (code) this._activatePatientMemory(code);
        if (this.state.booking.patientCode) {
            this._activatePatientMemory(this.state.booking.patientCode);
        }
    }

    // ── Navigation ────────────────────────────────────────────────────────────

    _goTo(view, crumbLabel) {
        if (crumbLabel) {
            this.state.breadcrumbs = [
                ...this.state.breadcrumbs,
                { label: crumbLabel, view: this.state.view },
            ];
        }
        this.state.view = view;
    }

    _goBack() {
        const crumbs = this.state.breadcrumbs;
        if (!crumbs.length) { this.state.view = VIEWS.MENU; return; }
        const last = crumbs[crumbs.length - 1];
        this.state.breadcrumbs = crumbs.slice(0, -1);
        this.state.view = last.view;
    }

    _goHome() {
        this.state.view        = VIEWS.MENU;
        this.state.breadcrumbs = [];
        this._resetBooking();
    }

    /**
     * Reset booking fields AND prune stale booking turns from Ollama history.
     *
     * CRITICAL FIX: We do NOT remove _fromMemory entries here.
     * Memory context stays intact so re-booking same patient works cleanly.
     * We only trim the real (non-memory) conversation to last 6 turns.
     */
    _resetBooking() {
        this.state.booking = {
            doctor: null, date: "", dateLabel: "",
            time: "", timeLabel: "", patientCode: "", notes: "",
        };
        this.state.bookedSlots = [];

        // Keep memory context; trim real conversation to last 6 turns only
        const memEntries  = this.history.filter(m => m._fromMemory);
        const realEntries = this.history.filter(m => !m._fromMemory).slice(-6);
        this.history = [...memEntries, ...realEntries];
    }

    toggleChat() {
        this.state.open = !this.state.open;
        if (this.state.open && !this.state.doctors.length) this._loadDoctors();
    }

    /**
     * Save memory then fully reset UI state.
     * Clearing _shownMemoryFor means next patient code typed will
     * trigger a fresh localStorage load.
     */
    clearChat() {
        this._saveCurrentMemory();
        this.history                 = [];
        this.state.messages          = [{ role: "assistant", text: WELCOME_TEXT, timestamp: Date.now() }];
        this.state.streamingText     = "";
        this.state.isStreaming       = false;
        this.state.activePatientCode = null;
        this.state.memoryLoaded      = false;
        this.state.memoryCount       = 0;
        // Reset shown-memory tracker so history shows again on next open
        this._shownMemoryFor = new Set();
        this._goHome();
    }

    onInputChange(ev)        { this.state.message              = ev.target.value; }
    onCodeChange(ev)         { this.state.booking.patientCode  = ev.target.value.toUpperCase(); }
    onNotesChange(ev)        { this.state.booking.notes        = ev.target.value; }
    onRecordsInputChange(ev) { this.state.recordsInput         = ev.target.value; }
    onOpenInputChange(ev)    { this.state.openInput            = ev.target.value; }

    onInputKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    // ── Voice ─────────────────────────────────────────────────────────────────

    toggleVoice() {
        if (!SpeechRecognitionClass) {
            alert("Voice input is not supported in this browser. Please use Chrome or Edge.");
            return;
        }
        if (this.state.listening) {
            if (this.currentRec) this.currentRec.stop();
            this.state.listening = false; this.currentRec = null; return;
        }
        const rec      = new SpeechRecognitionClass();
        rec.continuous = false; rec.interimResults = false;
        rec.lang       = "en-US"; rec.maxAlternatives = 1;
        rec.onresult   = (ev) => {
            this.state.message   = ev.results[0][0].transcript;
            this.state.listening = false; this.currentRec = null;
            this.sendMessage();
        };
        rec.onerror = rec.onend = () => {
            this.state.listening = false; this.currentRec = null;
        };
        this.currentRec = rec; this.state.listening = true; rec.start();
    }

    isSlotBooked(value) { return this.state.bookedSlots.includes(value); }

    _pushAssistant(text) {
        this.state.messages = [
            ...this.state.messages,
            { role: "assistant", text, timestamp: Date.now() },
        ];
    }
    _pushUser(text) {
        this.state.messages = [
            ...this.state.messages,
            { role: "user", text, timestamp: Date.now() },
        ];
    }

    // ── BOOKING FLOW ──────────────────────────────────────────────────────────

    openBookFlow() {
        this._resetBooking();
        this._goTo(VIEWS.BOOK_DOCTOR, "Menu");
    }

    selectDoctor(doc) {
        if (!doc.is_available) return;
        this.state.booking.doctor = doc;
        this._goTo(VIEWS.BOOK_DATE, "Book");
    }

    selectDate(chip) {
        this.state.booking.date      = chip.value;
        this.state.booking.dateLabel = `${chip.label} ${chip.num} ${chip.month}`;
        this.state.booking.time      = "";
        this._goTo(VIEWS.BOOK_TIME, chip.label);
        this._loadBookedSlots();
    }

    selectTime(slot) {
        if (this.isSlotBooked(slot.value)) return;
        this.state.booking.time      = slot.value;
        this.state.booking.timeLabel = slot.label;
        this._goTo(VIEWS.BOOK_PATIENT, this.state.booking.timeLabel);
    }

    goToNotes() {
        const code = normCode(this.state.booking.patientCode);
        if (!code) { alert("Please enter a patient code."); return; }
        this.state.booking.patientCode = code;
        // Load memory when patient enters code during booking
        // _activatePatientMemory handles dedup — safe to call every time
        this._activatePatientMemory(code);
        this._goTo(VIEWS.BOOK_NOTES, `Patient: ${code}`);
    }

    skipNotes()   { this.state.booking.notes = ""; this._goTo(VIEWS.BOOK_CONFIRM, "Notes"); }
    goToConfirm() { this._goTo(VIEWS.BOOK_CONFIRM, "Notes"); }

    get bookingDatetime() {
        const b = this.state.booking;
        return `${b.date} ${b.time}:00`;
    }

    /**
     * Confirm booking.
     *
     * FIX: After booking:
     *   1. Push confirmation to chat
     *   2. Save memory (includes confirmation message)
     *   3. _resetBooking() clears booking fields & trims Ollama history
     *      but KEEPS memory context — so same patient can re-book cleanly
     *   4. _shownMemoryFor still has the patient's code, so re-opening
     *      booking flow won't re-show the history popup
     */
    async confirmBooking() {
        const b = this.state.booking;
        if (!b.doctor || !b.date || !b.time || !b.patientCode) return;
        this.state.loading = true;
        try {
            const data = await this._post("/api/v19/chatbot/message", {
                direct_booking: {
                    patient_code:         b.patientCode,
                    doctor_name:          b.doctor.name,
                    appointment_datetime: this.bookingDatetime,
                    notes:                b.notes,
                },
                tz_name: this.tz,
            });
            const d           = data?.data ?? {};
            const reply       = d.reply       ?? "Booking failed.";
            const action      = d.action      ?? null;
            const action_data = d.action_data ?? {};

            this._pushAssistant(reply);
            this.history.push({ role: "assistant", content: reply });

            // Save BEFORE reset — confirmation message is included in memory
            this._saveCurrentMemory();

            // Reset booking state; memory context preserved for re-booking
            this._resetBooking();

            this._goTo(VIEWS.CHAT, "Confirm");
            if (action) setTimeout(() => this._handleAction(action, action_data), 1400);
        } catch (e) {
            this._pushAssistant("❌ Booking failed. Please try again.");
            this._goTo(VIEWS.CHAT, "Confirm");
        } finally {
            this.state.loading = false;
        }
    }

    // ── RECORDS FLOW ──────────────────────────────────────────────────────────

    openRecordsFlow() { this.state.recordsInput = ""; this._goTo(VIEWS.RECORDS_TYPE, "Menu"); }
    setRecordsType(t) { this.state.recordsType = t; }

    async fetchRecords() {
        const inp = this.state.recordsInput.trim();
        if (!inp) { alert("Please enter a patient code or doctor name."); return; }
        this.state.loading = true;
        this._goTo(VIEWS.CHAT, "Records");
        if (this.state.recordsType === "patient") this._activatePatientMemory(inp);
        try {
            const data = await this._post("/api/v19/chatbot/records", {
                type: this.state.recordsType, identifier: inp, tz_name: this.tz,
            });
            this._pushAssistant(data.reply ?? "No records found.");
            this._saveCurrentMemory();
        } catch (e) {
            this._pushAssistant("❌ Error fetching records. Please try again.");
        } finally {
            this.state.loading = false;
        }
    }

    // ── AVAILABILITY FLOW ─────────────────────────────────────────────────────

    openAvailFlow() {
        this.state.availDoctor = null; this.state.availDate = "";
        this._goTo(VIEWS.AVAIL_DOCTOR, "Menu");
    }
    selectAvailDoctor(doc) { this.state.availDoctor = doc; this._goTo(VIEWS.AVAIL_DATE, doc.name); }

    async checkAvail(date) {
        const doc = this.state.availDoctor;
        if (!doc) return;
        this.state.loading = true;
        this._goTo(VIEWS.CHAT, "Availability");
        try {
            const data = await this._post("/api/v19/chatbot/availability", {
                doctor_name: doc.name, date: date || "", tz_name: this.tz,
            });
            this._pushAssistant(data.reply ?? "No availability info.");
            this._saveCurrentMemory();
        } catch (e) {
            this._pushAssistant("❌ Error checking availability.");
        } finally {
            this.state.loading = false;
        }
    }

    // ── NAV FLOW ──────────────────────────────────────────────────────────────

    openNavFlow() { this._goTo(VIEWS.NAV, "Menu"); }
    doNavigate(page) { this._navigateTo(page); }

    // ── OPEN RECORD FLOW ──────────────────────────────────────────────────────

    openOpenFlow() { this.state.openInput = ""; this._goTo(VIEWS.OPEN_TYPE, "Menu"); }
    setOpenType(t) { this.state.openType  = t; }

    async doOpenRecord() {
        const inp = this.state.openInput.trim();
        if (!inp) { alert("Please enter a code or name."); return; }
        this.state.loading = true;
        this._goTo(VIEWS.CHAT, "Open Record");
        if (this.state.openType === "patient") this._activatePatientMemory(inp);
        try {
            const data = await this._post("/api/v19/chatbot/open_record", {
                type: this.state.openType, identifier: inp,
            });
            this._pushAssistant(data.reply ?? "Record not found.");
            this._saveCurrentMemory();
            if (data.action) setTimeout(() => this._handleAction(data.action, data.action_data || {}), 800);
        } catch (e) {
            this._pushAssistant("❌ Error opening record.");
        } finally {
            this.state.loading = false;
        }
    }

    // ── Core navigation ───────────────────────────────────────────────────────

    _navigateTo(page) {
        const route = PAGE_ROUTES[page];
        if (!route) { console.warn("Unknown page:", page); return; }
        this.state.open = false;
        this.action.doAction({
            type:      "ir.actions.act_window",
            name:      route.name,
            res_model: route.model,
            view_mode: route.view_mode,
            views:     route.view_mode.split(",").map(v => [false, v.trim()]),
            target:    "current",
        });
    }

    _openRecord(model, recordId) {
        const id = parseInt(recordId, 10);
        if (!model || !id) { console.error("_openRecord: invalid", model, recordId); return; }
        this.state.open = false;
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: model,
            res_id:    id,
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    _handleAction(action, action_data) {
        if (!action) return;
        if (action === "open_appointment" && action_data?.appointment_id) {
            this._openRecord("clinic.appointment", action_data.appointment_id);
        } else if (action === "open_record" && action_data?.model && action_data?.record_id) {
            this._openRecord(action_data.model, action_data.record_id);
        } else if (action === "navigate" && action_data?.page) {
            this._navigateTo(action_data.page);
        }
    }

    // ── Free-text chat ────────────────────────────────────────────────────────

    async sendMessage() {
        const text = this.state.message.trim();
        if (!text || this.state.loading) return;

        this._pushUser(text);
        this.history.push({ role: "user", content: text });
        this.state.message = "";
        this.state.loading = true;

        if (this.state.view !== VIEWS.CHAT) this._goTo(VIEWS.CHAT, "");

        this._checkAndActivateMemory(text);

        try {
            await this._sendStreaming(text);
        } catch (err) {
            console.error("sendMessage error:", err);
            this._pushAssistant("⚠️ Connection error. Make sure Ollama is running and try again.");
        } finally {
            this.state.loading       = false;
            this.state.isStreaming   = false;
            this.state.streamingText = "";
        }

        this._saveCurrentMemory();
    }

    async _sendStreaming(text) {
        // Strip _fromMemory before sending — server only needs role+content
        const historyForServer = this.history.map(({ role, content }) => ({ role, content }));

        let res;
        try {
            res = await fetch("/api/v19/chatbot/stream", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ message: text, history: historyForServer, tz_name: this.tz }),
            });
        } catch (e) {
            this._pushAssistant("⚠️ Cannot reach server. Please try again.");
            return;
        }

        if (!res.ok || !res.body) {
            this._pushAssistant("⚠️ Server error. Please try again.");
            return;
        }

        this.state.isStreaming   = true;
        this.state.streamingText = "";

        const reader  = res.body.getReader();
        const decoder = new TextDecoder();
        let fullText    = "";
        let action      = null;
        let action_data = {};
        let store_msg   = null;

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const lines = decoder.decode(value, { stream: true }).split("\n");
                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const dataStr = line.slice(6).trim();
                    if (dataStr === "[DONE]") break;
                    try {
                        const parsed = JSON.parse(dataStr);
                        if (parsed.token      !== undefined) { fullText += parsed.token; this.state.streamingText = fullText; }
                        if (parsed.action      !== undefined) action      = parsed.action;
                        if (parsed.action_data !== undefined) action_data = parsed.action_data;
                        if (parsed.store_msg   !== undefined) store_msg   = parsed.store_msg;
                    } catch {
                        fullText += dataStr;
                        this.state.streamingText = fullText;
                    }
                }
            }
        } catch {}
        finally { reader.cancel().catch(() => {}); }

        const finalText = fullText || this.state.streamingText;
        this.state.isStreaming   = false;
        this.state.streamingText = "";

        if (finalText) this._pushAssistant(finalText);

        const histContent = store_msg !== null ? store_msg : (finalText || "");
        this.history.push({ role: "assistant", content: histContent });

        if (action) setTimeout(() => this._handleAction(action, action_data), 900);
    }

    _scrollToBottom() {
        const el = this.messagesRef.el;
        if (el) el.scrollTop = el.scrollHeight;
    }

    formatText(raw) {
        const html = String(raw)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
            .replace(/\n/g, "<br>");
        return markup(html);
    }

    get isMenu()        { return this.state.view === VIEWS.MENU; }
    get isChat()        { return this.state.view === VIEWS.CHAT; }
    get isBookDoctor()  { return this.state.view === VIEWS.BOOK_DOCTOR; }
    get isBookDate()    { return this.state.view === VIEWS.BOOK_DATE; }
    get isBookTime()    { return this.state.view === VIEWS.BOOK_TIME; }
    get isBookPatient() { return this.state.view === VIEWS.BOOK_PATIENT; }
    get isBookNotes()   { return this.state.view === VIEWS.BOOK_NOTES; }
    get isBookConfirm() { return this.state.view === VIEWS.BOOK_CONFIRM; }
    get isRecordsType() { return this.state.view === VIEWS.RECORDS_TYPE; }
    get isAvailDoctor() { return this.state.view === VIEWS.AVAIL_DOCTOR; }
    get isAvailDate()   { return this.state.view === VIEWS.AVAIL_DATE; }
    get isNav()         { return this.state.view === VIEWS.NAV; }
    get isOpenType()    { return this.state.view === VIEWS.OPEN_TYPE; }
    get showBreadcrumb(){ return this.state.breadcrumbs.length > 0; }
}

registry.category("systray").add("clinic_chatbot", {
    Component: ClinicChatbot,
}, { sequence: 1 });

export { ClinicChatbot };