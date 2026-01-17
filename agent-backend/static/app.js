const form = document.querySelector(".composer");
const chat = document.querySelector(".chat");
const input = form.querySelector("input[name='message']");
const userIdInput = form.querySelector("input[name='user_id']");
const debugPanel = document.querySelector(".debug");

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

function appendMessage(role, text, time) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = time;

  wrapper.appendChild(bubble);
  wrapper.appendChild(meta);
  chat.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
}

function renderDebug(debug, events) {
  if (!debugPanel || !debug) return;
  const mem0Query = debugPanel.querySelector(".debug-block .value");
  const mem0Type = debugPanel.querySelectorAll(".debug-block .value")[1];
  if (mem0Query) mem0Query.textContent = debug.mem0.query || "(none)";
  if (mem0Type) mem0Type.textContent = debug.mem0.type || "(none)";

  const lists = debugPanel.querySelectorAll(".debug-list");
  const mem0List = lists[0];
  const toolList = lists[1];
  const dbList = lists[2];
  const eventList = lists[3];

  mem0List.innerHTML = "";
  if (debug.mem0.results && debug.mem0.results.length) {
    debug.mem0.results.forEach((item) => {
      const div = document.createElement("div");
      div.className = "debug-item";
      div.innerHTML = `<p class="value">${escapeHtml(item.memory || "")}</p><p class="label">score: ${item.score}</p>`;
      mem0List.appendChild(div);
    });
  } else {
    mem0List.innerHTML = '<p class="label">No memories retrieved.</p>';
  }

  toolList.innerHTML = "";
  if (debug.tools && debug.tools.length) {
    debug.tools.forEach((tool) => {
      const div = document.createElement("div");
      div.className = "debug-item";
      div.innerHTML = `<p class="value">${escapeHtml(tool.tool)}</p><p class="label">${escapeHtml(JSON.stringify(tool.args))}</p>`;
      toolList.appendChild(div);
    });
  } else {
    toolList.innerHTML = '<p class="label">No tool calls.</p>';
  }

  dbList.innerHTML = "";
  if (debug.db && debug.db.length) {
    debug.db.forEach((change) => {
      const div = document.createElement("div");
      div.className = "debug-item";
      div.innerHTML = `<p class="label">${escapeHtml(JSON.stringify(change))}</p>`;
      dbList.appendChild(div);
    });
  } else {
    dbList.innerHTML = '<p class="label">No DB changes.</p>';
  }


  if (eventList) {
    eventList.innerHTML = "";
    if (events && events.length) {
      events.forEach((event) => {
        const div = document.createElement("div");
        div.className = "debug-item";
        div.innerHTML = `<p class="value">${escapeHtml(event.event_type || "")}</p><p class="label">${escapeHtml(event.created_at || "")}</p>`;
        eventList.appendChild(div);
      });
    } else {
      eventList.innerHTML = '<p class="label">No events.</p>';
    }
  }

  const intentLabel = debugPanel.querySelector("header span");
  if (intentLabel) {
    intentLabel.textContent = `Intent: ${debug.intent || ""}`;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  const userId = userIdInput.value.trim() || "demo-user";
  input.value = "";
  appendMessage("user", message, new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));

  const formData = new FormData();
  formData.append("message", message);
  formData.append("user_id", userId);

  const response = await fetch("/chat", {
    method: "POST",
    headers: { "x-requested-with": "fetch" },
    body: formData,
  });

  if (!response.ok) {
    appendMessage("assistant", "Something went wrong. Try again.", new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
    return;
  }

  const payload = await response.json();
  appendMessage("assistant", payload.assistant.text, payload.assistant.time);
  renderDebug(payload.debug, payload.events);
  if (window.history && window.history.replaceState) {
    window.history.replaceState(null, "", "/");
  }
});
