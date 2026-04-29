(function () {
  let supportSessionNo = localStorage.getItem("support_session_no") || "";
  let supportSocket = null;

  const style = document.createElement("style");
  style.innerHTML = `
    #supportBtn{
      position:fixed;right:22px;bottom:22px;width:58px;height:58px;
      border-radius:50%;background:#6366f1;color:#fff;border:0;
      box-shadow:0 10px 30px rgba(0,0,0,.35);font-size:24px;
      cursor:pointer;z-index:99999;
    }
    #supportBox{
      position:fixed;right:22px;bottom:92px;width:340px;height:500px;
      max-width:calc(100vw - 44px);background:#fff;color:#111827;
      border-radius:18px;box-shadow:0 20px 60px rgba(0,0,0,.35);
      z-index:99999;display:none;overflow:hidden;font-family:Arial;
    }
    .support-head{
      background:#111827;color:#fff;padding:14px 16px;font-weight:700;
      display:flex;justify-content:space-between;align-items:center;
    }
    .support-close{background:transparent;color:#fff;border:0;font-size:20px;cursor:pointer}
    .support-body{padding:14px}
    .support-input,.support-textarea{
      width:100%;box-sizing:border-box;padding:10px;border:1px solid #ddd;
      border-radius:10px;margin-bottom:10px;color:#111;background:#fff;
    }
    .support-textarea{height:110px;resize:none}
    .support-primary{
      width:100%;padding:11px;border:0;border-radius:10px;
      background:#6366f1;color:#fff;font-weight:700;cursor:pointer;
    }
    #supportChat{display:none;height:446px;flex-direction:column}
    #supportMessages{height:370px;overflow:auto;padding:12px;background:#f8fafc}
    .support-sendbar{display:flex;gap:8px;padding:10px;border-top:1px solid #e5e7eb}
    .support-sendbar input{flex:1;padding:10px;border:1px solid #ddd;border-radius:10px}
    .support-sendbar button{padding:10px 13px;border:0;border-radius:10px;background:#111827;color:#fff;cursor:pointer}
    .support-msg{margin:8px 0}
    .support-msg.me{text-align:right}
    .support-bubble{
      display:inline-block;max-width:78%;padding:9px 11px;border-radius:12px;
      word-break:break-word;text-align:left;
    }
    .support-bubble.me{background:#6366f1;color:#fff}
    .support-bubble.admin{background:#fff;color:#111827;border:1px solid #e5e7eb}
    .support-img{max-width:180px;border-radius:10px;display:block}
    #supportUnread{
      position:absolute;right:-2px;top:-2px;background:#ef4444;color:#fff;
      width:18px;height:18px;border-radius:50%;font-size:12px;
      display:none;align-items:center;justify-content:center;
    }
  `;
  document.head.appendChild(style);

  const root = document.createElement("div");
  root.innerHTML = `
    <button id="supportBtn">💬<span id="supportUnread">1</span></button>

    <div id="supportBox">
      <div class="support-head">
        <span>在线客服</span>
        <button class="support-close" id="supportClose">×</button>
      </div>

      <div id="supportStart" class="support-body">
        <input id="supportEmail" class="support-input" placeholder="你的邮箱，可选">
        <input id="supportOrderNo" class="support-input" placeholder="订单号，可选">
        <textarea id="supportFirstMessage" class="support-textarea" placeholder="请输入你要咨询的问题"></textarea>
        <button id="supportStartBtn" class="support-primary">开始咨询</button>
        <div id="supportStartMsg" style="font-size:13px;color:#b91c1c;margin-top:8px;"></div>
      </div>

      <div id="supportChat">
        <div id="supportMessages"></div>
        <div class="support-sendbar">
          <input id="supportInput" placeholder="输入消息...">
          <input id="supportImage" type="file" accept="image/*" style="display:none">
          <button id="supportImgBtn">图</button>
          <button id="supportSendBtn">发送</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(root);

  const btn = document.getElementById("supportBtn");
  const box = document.getElementById("supportBox");
  const closeBtn = document.getElementById("supportClose");
  const unread = document.getElementById("supportUnread");

  function showUnread() {
    if (box.style.display !== "block") {
      unread.style.display = "flex";
    }
  }

  function clearUnread() {
    unread.style.display = "none";
  }

  function notify(title, body) {
    try {
      if (Notification.permission === "granted") {
        new Notification(title, { body });
      } else if (Notification.permission !== "denied") {
        Notification.requestPermission();
      }
    } catch (e) {}
  }

  function playSound() {
    try {
      const audio = new Audio("https://actions.google.com/sounds/v1/alarms/beep_short.ogg");
      audio.play().catch(() => {});
    } catch (e) {}
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function appendMessage(sender, content) {
    const wrap = document.getElementById("supportMessages");
    const isMe = sender === "customer";

    const row = document.createElement("div");
    row.className = "support-msg " + (isMe ? "me" : "admin");

    let html = escapeHtml(content || "");

    if (String(content || "").startsWith("[img]")) {
      const url = String(content).replace("[img]", "");
      html = `<img class="support-img" src="${escapeHtml(url)}">`;
    }

    row.innerHTML = `
      <div class="support-bubble ${isMe ? "me" : "admin"}">${html}</div>
    `;

    wrap.appendChild(row);
    wrap.scrollTop = wrap.scrollHeight;
  }

  async function openChat(sessionNo) {
    document.getElementById("supportStart").style.display = "none";
    document.getElementById("supportChat").style.display = "flex";

    const messagesBox = document.getElementById("supportMessages");
    messagesBox.innerHTML = "";

    try {
      const res = await fetch(`/support/sessions/${encodeURIComponent(sessionNo)}/messages`);
      const data = await res.json();
      (data.items || []).forEach(m => appendMessage(m.sender_type, m.content));
    } catch (e) {}

    connectSocket(sessionNo);
  }

  function connectSocket(sessionNo) {
    if (supportSocket) {
      try { supportSocket.close(); } catch (e) {}
    }

    const protocol = location.protocol === "https:" ? "wss" : "ws";
    supportSocket = new WebSocket(`${protocol}://${location.host}/ws/support/customer/${encodeURIComponent(sessionNo)}`);

    supportSocket.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "message" && data.message) {
        appendMessage(data.message.sender_type, data.message.content);

        if (data.message.sender_type === "admin") {
          showUnread();
          playSound();
          notify("客服新回复", data.message.content || "你有一条新消息");
        }
      }
    };

    supportSocket.onclose = () => {
      setTimeout(() => {
        if (supportSessionNo) connectSocket(supportSessionNo);
      }, 3000);
    };
  }

  async function startChat() {
    const email = document.getElementById("supportEmail").value.trim();
    const orderNo = document.getElementById("supportOrderNo").value.trim();
    const firstMessage = document.getElementById("supportFirstMessage").value.trim();
    const msgBox = document.getElementById("supportStartMsg");

    if (!firstMessage) {
      msgBox.innerText = "请输入咨询内容";
      return;
    }

    msgBox.innerText = "正在连接客服...";

    try {
      const res = await fetch("/support/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_email: email || null,
          order_no: orderNo || null,
          first_message: firstMessage
        })
      });

      const data = await res.json();

      if (!res.ok) {
        msgBox.innerText = data.detail || "创建客服会话失败";
        return;
      }

      supportSessionNo = data.session.session_no;
      localStorage.setItem("support_session_no", supportSessionNo);
      openChat(supportSessionNo);

    } catch (e) {
      msgBox.innerText = "连接失败：" + e.message;
    }
  }

  function sendMessage() {
    const input = document.getElementById("supportInput");
    const content = input.value.trim();

    if (!content) return;

    if (!supportSocket || supportSocket.readyState !== WebSocket.OPEN) {
      alert("客服连接中，请稍后再试");
      return;
    }

    supportSocket.send(JSON.stringify({ content }));
    input.value = "";
  }

  function sendImage(file) {
    if (!file) return;

    const reader = new FileReader();

    reader.onload = () => {
      const base64 = reader.result;

      if (!supportSocket || supportSocket.readyState !== WebSocket.OPEN) {
        alert("客服连接中，请稍后再试");
        return;
      }

      supportSocket.send(JSON.stringify({
        content: "[img]" + base64
      }));
    };

    reader.readAsDataURL(file);
  }

  btn.onclick = () => {
    box.style.display = box.style.display === "block" ? "none" : "block";
    clearUnread();

    if (box.style.display === "block" && supportSessionNo) {
      openChat(supportSessionNo);
    }
  };

  closeBtn.onclick = () => {
    box.style.display = "none";
  };

  document.getElementById("supportStartBtn").onclick = startChat;
  document.getElementById("supportSendBtn").onclick = sendMessage;

  document.getElementById("supportInput").addEventListener("keydown", e => {
    if (e.key === "Enter") sendMessage();
  });

  document.getElementById("supportImgBtn").onclick = () => {
    document.getElementById("supportImage").click();
  };

  document.getElementById("supportImage").onchange = e => {
    sendImage(e.target.files[0]);
    e.target.value = "";
  };
})();