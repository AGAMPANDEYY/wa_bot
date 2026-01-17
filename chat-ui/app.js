const chat = document.getElementById("chat");
const input = document.getElementById("input");
const send = document.getElementById("send");
const upcoming = document.getElementById("upcoming");

const quickButtons = document.querySelectorAll(".quick-actions button");

const replies = [
  "All set. I will keep it on your radar.",
  "Noted. I will remind you at the right time.",
  "Got it. Anything else you want to track?",
];

function nowLabel() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function appendMessage(text, role) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("p");
  bubble.className = "bubble";
  bubble.textContent = text;

  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = nowLabel();

  wrapper.appendChild(bubble);
  wrapper.appendChild(meta);
  chat.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
}

function addUpcoming(title, time) {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div>
      <p class="card-title">${title}</p>
      <p class="card-sub">${time}</p>
    </div>
    <span class="pill">Active</span>
  `;
  upcoming.prepend(card);
}

function generateReply(text) {
  const lower = text.toLowerCase();
  if (lower.includes("remind me")) {
    return "Perfect. I will add that reminder and follow up.";
  }
  if (lower.includes("snooze")) {
    return "Okay, snoozed for 10 minutes.";
  }
  if (lower.includes("reschedule")) {
    return "Updated. I will ping you at the new time.";
  }
  if (lower.includes("coming up") || lower.includes("today")) {
    return "You have rent tomorrow morning and one follow-up Monday at 10 AM.";
  }
  return replies[Math.floor(Math.random() * replies.length)];
}

function handleSend(text) {
  if (!text) return;
  appendMessage(text, "user");

  if (text.toLowerCase().includes("remind me to")) {
    const title = text.replace(/remind me to/i, "").trim() || "New reminder";
    addUpcoming(title, "Today, 6:00 PM");
  }

  const typing = document.createElement("div");
  typing.className = "message bot";
  typing.innerHTML = `<p class="bubble">Typing...</p><span class="meta">${nowLabel()}</span>`;
  chat.appendChild(typing);
  chat.scrollTop = chat.scrollHeight;

  setTimeout(() => {
    typing.remove();
    appendMessage(generateReply(text), "bot");
  }, 700);
}

send.addEventListener("click", () => {
  const text = input.value.trim();
  input.value = "";
  handleSend(text);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    const text = input.value.trim();
    input.value = "";
    handleSend(text);
  }
});

quickButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const text = button.getAttribute("data-quick") || "";
    handleSend(text);
  });
});
