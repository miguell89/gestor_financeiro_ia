const sidebarToggle = document.querySelector(".sidebar-toggle");

const MONTH_LABELS = {
  1: "Janeiro",
  2: "Fevereiro",
  3: "Marco",
  4: "Abril",
  5: "Maio",
  6: "Junho",
  7: "Julho",
  8: "Agosto",
  9: "Setembro",
  10: "Outubro",
  11: "Novembro",
  12: "Dezembro",
};

const normalizePeriod = (month, year) => {
  const now = new Date();
  const safeMonth = Math.min(Math.max(Number(month || now.getMonth() + 1), 1), 12);
  const safeYear = Math.min(Math.max(Number(year || now.getFullYear()), 2000), 2100);
  return { month: safeMonth, year: safeYear };
};

const getSelectedPeriod = () => {
  const params = new URLSearchParams(window.location.search);
  const stored = JSON.parse(localStorage.getItem("selected-period") || "{}");
  return normalizePeriod(
    params.get("month") || document.body.dataset.selectedMonth || stored.month,
    params.get("year") || document.body.dataset.selectedYear || stored.year
  );
};

const selectedPeriodParams = () => {
  const { month, year } = getSelectedPeriod();
  const params = new URLSearchParams();
  params.set("month", month);
  params.set("year", year);
  return params;
};

const withSelectedPeriod = (url) => {
  const [path, query = ""] = url.split("?");
  const params = new URLSearchParams(query);
  selectedPeriodParams().forEach((value, key) => params.set(key, value));
  return `${path}?${params.toString()}`;
};

const updatePeriodHeader = (month, year) => {
  document.body.dataset.selectedMonth = month;
  document.body.dataset.selectedYear = year;
  document.body.dataset.selectedLabel = `${MONTH_LABELS[month]} de ${year}`;
  document.querySelectorAll("[data-period-form]").forEach((form) => {
    if (form.elements.month) form.elements.month.value = String(month);
    if (form.elements.year) form.elements.year.value = String(year);
  });
  document.querySelectorAll("a[href]").forEach((link) => {
    const rawHref = link.getAttribute("href");
    if (!rawHref || rawHref.startsWith("#") || rawHref.startsWith("mailto:") || rawHref.includes("/logout")) return;
    const url = new URL(link.href, window.location.origin);
    if (url.origin !== window.location.origin || url.pathname.startsWith("/api/") || url.pathname === "/login") return;
    url.searchParams.set("month", month);
    url.searchParams.set("year", year);
    if (link.classList.contains("period-nav")) {
      const delta = link.title === "Mes anterior" ? -1 : 1;
      const shifted = normalizePeriod(month + delta, year);
      if (month + delta < 1) shifted.year = year - 1;
      if (month + delta > 12) shifted.year = year + 1;
      shifted.month = month + delta < 1 ? 12 : month + delta > 12 ? 1 : month + delta;
      url.searchParams.set("month", shifted.month);
      url.searchParams.set("year", shifted.year);
    }
    if (link.classList.contains("period-current")) {
      const now = new Date();
      url.searchParams.set("month", now.getMonth() + 1);
      url.searchParams.set("year", now.getFullYear());
    }
    link.href = `${url.pathname}?${url.searchParams.toString()}`;
  });
};

const setSelectedPeriod = (month, year, options = {}) => {
  const period = normalizePeriod(month, year);
  localStorage.setItem("selected-period", JSON.stringify(period));
  updatePeriodHeader(period.month, period.year);
  const params = new URLSearchParams(window.location.search);
  params.set("month", period.month);
  params.set("year", period.year);
  params.delete("page");
  const targetUrl = `${window.location.pathname}?${params.toString()}`;
  window.history.pushState({ period }, "", targetUrl);
  window.dispatchEvent(new CustomEvent("periodChanged", { detail: period }));
  if (options.navigate) window.location.assign(targetUrl);
};

window.setSelectedPeriod = setSelectedPeriod;

const initialPeriod = getSelectedPeriod();
localStorage.setItem("selected-period", JSON.stringify(initialPeriod));
updatePeriodHeader(initialPeriod.month, initialPeriod.year);

const selectedPeriodParamsFromUrl = () => {
  return getSelectedPeriod();
};

const selectedPeriodFirstDate = () => {
  const { month, year } = getSelectedPeriod();
  return `${year}-${String(month).padStart(2, "0")}-01`;
};

document.querySelectorAll("[data-period-form]").forEach((form) => {
  form.querySelectorAll("select").forEach((field) => {
    field.addEventListener("change", () => {
      setSelectedPeriod(form.elements.month.value, form.elements.year.value);
    });
  });
});

document.querySelectorAll(".period-nav, .period-current").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    const url = new URL(link.href);
    setSelectedPeriod(url.searchParams.get("month"), url.searchParams.get("year"));
  });
});

if (sidebarToggle) {
  const collapsed = localStorage.getItem("sidebar-collapsed") === "true";
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  sidebarToggle.setAttribute("aria-expanded", String(!collapsed));

  sidebarToggle.addEventListener("click", () => {
    const isCollapsed = document.body.classList.toggle("sidebar-collapsed");
    localStorage.setItem("sidebar-collapsed", String(isCollapsed));
    sidebarToggle.setAttribute("aria-expanded", String(!isCollapsed));
  });
}

document.querySelectorAll(".bar-row i").forEach((bar) => {
  const width = bar.style.width;
  bar.style.width = "0%";
  window.requestAnimationFrame(() => {
    bar.style.transition = "width 700ms ease";
    bar.style.width = width;
  });
});

const refreshButton = document.querySelector(".refresh-dashboard");

if (refreshButton) {
  refreshButton.addEventListener("click", async () => {
    refreshButton.textContent = "Atualizando...";
    try {
      const response = await fetch(withSelectedPeriod("/api/dashboard"));
      if (!response.ok) throw new Error("Falha ao atualizar");
      await response.json();
      window.location.reload();
    } catch (error) {
      refreshButton.textContent = "Erro ao atualizar";
      setTimeout(() => {
        refreshButton.textContent = "Atualizar Dashboard";
      }, 1800);
    }
  });
}

if (document.querySelector(".dashboard-shell") || document.querySelector(".reports-page") || document.querySelector(".assistant-page") || document.querySelector(".goals-page")) {
  window.addEventListener("periodChanged", () => window.location.reload());
}

const reportsPage = document.querySelector("[data-reports-page]");

if (reportsPage) {
  const brl = (value) =>
    Number(value || 0).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
    });

  const canvas = document.getElementById("report-evolution-chart");
  const rangeSelect = document.querySelector("[data-report-range]");

  const drawLineChart = (points) => {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    const padding = { top: 26, right: 24, bottom: 48, left: 78 };
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "rgba(8, 16, 31, 0.98)";
    ctx.fillRect(0, 0, width, height);

    const values = points.flatMap((item) => [item.receitas, item.despesas, item.saldo]);
    const max = Math.max(...values, 1000);
    const min = Math.min(...values, 0);
    const range = Math.max(max - min, 1);
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const xFor = (index) => padding.left + (plotWidth / Math.max(points.length - 1, 1)) * index;
    const yFor = (value) => padding.top + plotHeight - ((value - min) / range) * plotHeight;

    ctx.strokeStyle = "rgba(121, 147, 197, 0.18)";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#a9b7d3";
    ctx.font = "13px Inter, sans-serif";
    for (let i = 0; i <= 4; i += 1) {
      const y = padding.top + (plotHeight / 4) * i;
      const value = max - (range / 4) * i;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      ctx.fillText(brl(value).replace(",00", ""), 10, y + 4);
    }

    const drawSeries = (key, color) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.beginPath();
      points.forEach((item, index) => {
        const x = xFor(index);
        const y = yFor(item[key]);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      points.forEach((item, index) => {
        const x = xFor(index);
        const y = yFor(item[key]);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fill();
      });
    };

    drawSeries("receitas", "#38f2a8");
    drawSeries("despesas", "#ff5e66");
    drawSeries("saldo", "#3478f6");

    ctx.fillStyle = "#c7d4ee";
    points.forEach((item, index) => {
      ctx.fillText(item.label, xFor(index) - 18, height - 16);
    });
  };

  const renderReports = (data) => {
    drawLineChart(data.evolution || []);
    document.querySelectorAll("[data-report-card]").forEach((element) => {
      const key = element.dataset.reportCard;
      if (!data.summary || !(key in data.summary)) return;
      element.textContent = key === "meta_atingida" ? `${Math.round(data.summary[key])}%` : brl(data.summary[key]);
    });
  };

  const loadReports = async () => {
    const params = selectedPeriodParams();
    params.set("range", rangeSelect?.value || "12");
    const response = await fetch(`/api/reports?${params.toString()}`);
    if (!response.ok) throw new Error("Erro ao carregar relatorios");
    renderReports(await response.json());
  };

  rangeSelect?.addEventListener("change", () => {
    loadReports().catch((error) => console.error("Erro da API", error));
  });

  loadReports().catch((error) => console.error("Erro da API", error));
}

document.querySelectorAll(".modal-open").forEach((button) => {
  button.addEventListener("click", () => {
    const modal = document.getElementById(button.dataset.modalTarget);
    if (modal) modal.hidden = false;
  });
});

document.querySelectorAll("[data-modal-close], .modal-backdrop").forEach((element) => {
  element.addEventListener("click", (event) => {
    if (event.target !== element) return;
    const modal = element.closest(".modal-backdrop") || element;
    modal.hidden = true;
  });
});

const adminUserForm = document.querySelector("[data-admin-user-form]");

if (adminUserForm) {
  const feedback = document.querySelector("[data-admin-user-feedback]");
  const usersBody = document.querySelector("[data-admin-users-body]");
  const adminModal = document.getElementById("admin-user-modal");
  const codeField = adminUserForm.querySelector("[data-admin-code-field]");
  const commandPreview = adminUserForm.querySelector("[data-admin-command-preview]");
  const generateCodeFlag = adminUserForm.querySelector("[data-admin-generate-code-flag]");
  const telegramStatusPreview = adminUserForm.querySelector("[data-admin-telegram-status]");
  const summary = (key) => adminUserForm.querySelector(`[data-admin-summary="${key}"]`);
  const pref = (key) => adminUserForm.querySelector(`[data-admin-pref="${key}"]`);
  const displayRole = (value) => (value === "admin" ? "Admin" : "Usuário");
  const displayStatus = (value) => (value === "inativo" ? "Inativo" : "Ativo");
  const randomCode = () => {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    let code = "GFI-";
    for (let index = 0; index < 6; index += 1) code += chars[Math.floor(Math.random() * chars.length)];
    return code;
  };
  const randomPassword = () => {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
    let value = "MGF-";
    for (let index = 0; index < 8; index += 1) value += chars[Math.floor(Math.random() * chars.length)];
    return value;
  };
  const setTelegramPreview = (code = "") => {
    if (codeField) codeField.value = code;
    if (commandPreview) commandPreview.textContent = code ? `/vincular ${code}` : "/vincular CODIGO";
    if (telegramStatusPreview) {
      telegramStatusPreview.textContent = code ? "Pendente" : "Não vinculado";
      telegramStatusPreview.className = `telegram-badge ${code ? "telegram-pendente" : "telegram-nao_conectado"}`;
    }
    const telegramSummary = summary("telegram_status");
    if (telegramSummary) {
      telegramSummary.textContent = code ? "Pendente" : "Não vinculado";
      telegramSummary.className = `telegram-badge ${code ? "telegram-pendente" : "telegram-nao_conectado"}`;
    }
    const codeSummary = summary("telegram_code");
    if (codeSummary) codeSummary.textContent = code || "-";
  };
  const updateAdminSummary = () => {
    const form = adminUserForm.elements;
    if (summary("name")) summary("name").textContent = form.name?.value || "-";
    if (summary("email")) summary("email").textContent = form.email?.value || "-";
    if (summary("role")) summary("role").textContent = displayRole(form.role?.value);
    if (summary("password")) summary("password").textContent = form.password?.value || "-";
    const statusElement = summary("status");
    if (statusElement) {
      statusElement.textContent = displayStatus(form.status?.value);
      statusElement.className = `status ${form.status?.value === "ativo" ? "pago" : "cancelado"}`;
    }
    ["receive_telegram_alerts", "receive_telegram_reports", "receive_telegram_bill_reminders", "receive_telegram_ai_analysis"].forEach((key) => {
      const element = pref(key);
      if (element) element.textContent = form[key]?.checked ? "Sim" : "Não";
    });
  };
  const userRow = (user) => `
    <tr data-user-row="${user.id}">
      <td>${user.id}</td>
      <td>${user.name || "-"}</td>
      <td>${user.email || "-"}</td>
      <td><em class="telegram-badge telegram-${user.telegram_status || "nao_conectado"}">${user.telegram_badge || "🔴 Não conectado"}</em></td>
      <td>${user.telegram_username ? `@${user.telegram_username}` : "-"}</td>
      <td><em class="status ${user.status === "ativo" ? "pago" : "cancelado"}">${user.status}</em></td>
      <td>${user.role}</td>
      <td>0</td>
      <td>${user.telegram_last_interaction || user.last_interaction_at || user.last_login_at || "-"}</td>
      <td class="actions-cell">
        <a href="/admin/usuarios/${user.id}">Detalhes</a>
        <a href="/admin/usuarios/${user.id}/editar">Editar</a>
        <form method="post" action="/admin/usuarios/${user.id}/toggle">
          <button>${user.status === "ativo" ? "Desativar" : "Ativar"}</button>
        </form>
      </td>
    </tr>`;

  adminUserForm.querySelector("[data-admin-generate-password]")?.addEventListener("click", () => {
    adminUserForm.elements.password.value = randomPassword();
    updateAdminSummary();
  });

  adminUserForm.querySelector("[data-admin-preview-code]")?.addEventListener("click", () => {
    setTelegramPreview(randomCode());
  });

  adminUserForm.querySelector("[data-admin-copy-code]")?.addEventListener("click", async () => {
    const value = codeField?.value;
    if (!value) return;
    try {
      await navigator.clipboard.writeText(`/vincular ${value}`);
      feedback.textContent = "Código copiado.";
    } catch (error) {
      feedback.textContent = "Copie manualmente o código exibido.";
    }
  });

  adminUserForm.addEventListener("input", updateAdminSummary);
  adminUserForm.addEventListener("change", updateAdminSummary);

  adminUserForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    feedback.textContent = "";
    const shouldGenerateCode = event.submitter?.dataset.adminSubmitMode === "telegram";
    if (generateCodeFlag) generateCodeFlag.value = shouldGenerateCode ? "1" : "0";
    const payload = Object.fromEntries(new FormData(adminUserForm).entries());
    payload.generate_telegram_code = shouldGenerateCode ? "1" : "0";
    ["receive_telegram_alerts", "receive_telegram_reports", "receive_telegram_bill_reminders", "receive_telegram_ai_analysis"].forEach((key) => {
      payload[key] = adminUserForm.elements[key]?.checked ? "1" : "0";
    });
    try {
      const response = await fetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Erro ao criar usuário");
      if (usersBody) usersBody.insertAdjacentHTML("afterbegin", userRow(data.user));
      if (data.telegram_code?.code) setTelegramPreview(data.telegram_code.code);
      feedback.textContent = shouldGenerateCode ? "Usuário criado e código Telegram gerado." : "Usuário criado com sucesso.";
      if (!shouldGenerateCode) {
        adminUserForm.reset();
        setTelegramPreview("");
        updateAdminSummary();
        setTimeout(() => {
          adminModal.hidden = true;
          feedback.textContent = "";
        }, 700);
      }
    } catch (error) {
      feedback.textContent = error.message;
    }
  });

  setTelegramPreview("");
  updateAdminSummary();
}

const quickCategoryModal = document.getElementById("quick-category-modal");
const quickCategoryForm = document.querySelector("[data-quick-category-form]");
let quickCategoryTarget = null;

const categoryTypeLabel = (value) =>
  ({
    receita: "Receita",
    despesa: "Despesa",
    conta_fixa: "Conta Fixa",
    geral: "Geral",
  }[value] || "Geral");

const openQuickCategoryModal = (select) => {
  quickCategoryTarget = select;
  quickCategoryForm.reset();
  quickCategoryForm.elements.color.value = "#38bdf8";
  quickCategoryForm.elements.type.value = select.dataset.categoryKind || "geral";
  quickCategoryModal.hidden = false;
  quickCategoryForm.elements.name.focus();
};

document.querySelectorAll("[data-category-select]").forEach((select) => {
  select.addEventListener("change", () => {
    if (select.value !== "__new__") return;
    select.value = "";
    openQuickCategoryModal(select);
  });
});

document.querySelectorAll("[data-quick-category-close]").forEach((button) => {
  button.addEventListener("click", () => {
    quickCategoryModal.hidden = true;
    if (quickCategoryTarget) quickCategoryTarget.value = "";
  });
});

if (quickCategoryForm) {
  quickCategoryForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const feedback = document.querySelector("[data-quick-category-feedback]");
    const payload = Object.fromEntries(new FormData(quickCategoryForm).entries());
    payload.active = "1";
    try {
      const response = await fetch("/api/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Erro ao criar categoria");
      if (quickCategoryTarget) {
        const option = document.createElement("option");
        option.value = quickCategoryTarget.name === "category" ? data.name : data.id;
        option.textContent = data.name;
        const newOption = quickCategoryTarget.querySelector("option[value='__new__']");
        quickCategoryTarget.insertBefore(option, newOption);
        quickCategoryTarget.value = option.value;
        quickCategoryTarget.dispatchEvent(new Event("change", { bubbles: true }));
      }
      quickCategoryModal.hidden = true;
      if (feedback) feedback.textContent = "";
    } catch (error) {
      if (feedback) feedback.textContent = error.message;
    }
  });
}

const categoriesSettingsPage = document.querySelector("[data-categories-settings]");

if (categoriesSettingsPage) {
  const form = document.querySelector("[data-category-admin-form]");
  const feedback = document.querySelector("[data-category-feedback]");
  const title = document.querySelector("[data-category-form-title]");
  const filter = document.querySelector("[data-category-filter]");

  const resetCategoryForm = () => {
    form.reset();
    form.elements.id.value = "";
    form.elements.color.value = "#38bdf8";
    form.elements.active.checked = true;
    title.textContent = "Nova categoria";
    feedback.textContent = "";
  };

  document.querySelector("[data-category-new]")?.addEventListener("click", resetCategoryForm);
  document.querySelector("[data-category-reset]")?.addEventListener("click", resetCategoryForm);

  filter?.addEventListener("change", () => {
    document.querySelectorAll("[data-category-row]").forEach((row) => {
      row.hidden = Boolean(filter.value) && row.dataset.type !== filter.value;
    });
  });

  document.addEventListener("click", async (event) => {
    const edit = event.target.closest("[data-category-edit]");
    const deactivate = event.target.closest("[data-category-deactivate]");
    const remove = event.target.closest("[data-category-delete]");

    if (edit) {
      const category = JSON.parse(edit.dataset.categoryEdit);
      form.elements.id.value = category.id;
      form.elements.name.value = category.name || "";
      form.elements.type.value = category.type || "geral";
      form.elements.icon.value = category.icon || "";
      form.elements.color.value = category.color || "#38bdf8";
      form.elements.monthly_limit.value = category.monthly_limit || 0;
      form.elements.active.checked = Boolean(Number(category.active));
      title.textContent = "Editar categoria";
      feedback.textContent = "";
    }

    if (deactivate) {
      const id = deactivate.dataset.categoryDeactivate;
      const response = await fetch(`/api/categories/${id}/deactivate`, { method: "PATCH" });
      if (!response.ok) return;
      window.location.reload();
    }

    if (remove) {
      const id = remove.dataset.categoryDelete;
      if (!window.confirm("Excluir esta categoria? Se estiver em uso, ela sera apenas bloqueada pela regra do sistema.")) return;
      const response = await fetch(`/api/categories/${id}`, { method: "DELETE" });
      if (response.status === 409) {
        const data = await response.json();
        feedback.textContent = data.error;
        return;
      }
      if (!response.ok) return;
      window.location.reload();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.active = form.elements.active.checked ? "1" : "0";
    const id = payload.id;
    delete payload.id;
    const response = await fetch(id ? `/api/categories/${id}` : "/api/categories", {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      feedback.textContent = data.error || "Erro ao salvar categoria";
      return;
    }
    window.location.reload();
  });
}

const goalsPage = document.querySelector("[data-goals-page]");

if (goalsPage) {
  const brl = (value) =>
    Number(value || 0).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
    });
  const goalModal = document.getElementById("goal-modal");
  const contributionModal = document.getElementById("goal-contribution-modal");
  const historyModal = document.getElementById("goal-history-modal");
  const goalForm = document.querySelector("[data-goal-form]");
  const contributionForm = document.querySelector("[data-goal-contribution-form]");
  const goalFeedback = document.querySelector("[data-goal-feedback]");
  const contributionFeedback = document.querySelector("[data-goal-contribution-feedback]");
  const modalTitle = document.querySelector("[data-goal-modal-title]");
  const simulatorExtra = document.querySelector("[data-goal-simulator-extra]");

  const parseDate = (value) => (value ? new Date(`${value}T00:00:00`) : null);
  const monthDiff = (start, end) => Math.max((end.getFullYear() - start.getFullYear()) * 12 + end.getMonth() - start.getMonth(), 0);
  const addMonths = (date, months) => {
    const next = new Date(date);
    next.setMonth(next.getMonth() + months);
    return next;
  };
  const shortMonth = (date) => date.toLocaleDateString("pt-BR", { month: "short", year: "numeric" }).replace(".", "");

  const setGoalType = (type) => {
    goalForm.elements.type.value = type;
    document.querySelectorAll("[data-goal-type]").forEach((button) => {
      button.classList.toggle("active", button.dataset.goalType === type);
    });
    const icon = goalForm.elements.icon;
    if (!icon.value) icon.value = type.slice(0, 1);
    syncGoalPreview();
  };

  const goalStatusFromNumbers = ({ percent, monthly, required, deadline }) => {
    if (percent >= 100) return { value: "concluida", label: "Concluida", tone: "success" };
    if (!deadline) return { value: "no_ritmo", label: "No ritmo", tone: "success" };
    if (monthly >= required && required > 0) return { value: "no_ritmo", label: "No ritmo", tone: "success" };
    if (monthly >= required * 0.7) return { value: "no_ritmo", label: "Atencao", tone: "warning" };
    return { value: "atrasada", label: "Atrasada", tone: "danger" };
  };

  const syncGoalPreview = () => {
    const name = goalForm.elements.name.value || "Nova meta";
    const type = goalForm.elements.type.value || "Reserva de emergencia";
    const target = Number(goalForm.elements.target_amount.value || 0);
    const current = Number(goalForm.elements.current_amount.value || 0);
    const monthly = Number(goalForm.elements.monthly_target_amount.value || 0);
    const color = goalForm.elements.color.value || "#8b5cf6";
    const icon = goalForm.elements.icon.value || name.slice(0, 1) || "G";
    const start = parseDate(goalForm.elements.start_date.value) || new Date();
    const deadline = parseDate(goalForm.elements.deadline_date.value);
    const missing = Math.max(target - current, 0);
    const percent = target ? Math.min(Math.round((current / target) * 100), 100) : 0;
    const monthsToDeadline = deadline ? Math.max(monthDiff(start, deadline), 1) : 0;
    const required = deadline && missing ? missing / monthsToDeadline : 0;
    const pace = monthly || required;
    const forecast = pace && missing ? addMonths(new Date(), Math.ceil(missing / pace)) : null;
    const extra = Number(simulatorExtra?.value || 0);
    const boostedPace = pace + extra;
    const boostedForecast = boostedPace && missing ? addMonths(new Date(), Math.ceil(missing / boostedPace)) : forecast;
    const delta = forecast && boostedForecast ? Math.max(monthDiff(boostedForecast, forecast), 0) : 0;
    const smartStatus = goalStatusFromNumbers({ percent, monthly: pace, required, deadline });

    goalForm.elements.status.value = smartStatus.value === "concluida" ? "concluida" : smartStatus.value;
    document.querySelector("[data-goal-preview-name]").textContent = name;
    document.querySelector("[data-goal-preview-type]").textContent = type;
    document.querySelector("[data-goal-preview-icon]").textContent = icon;
    document.querySelector("[data-goal-preview-icon]").style.background = color;
    document.querySelector("[data-goal-preview-status]").textContent = smartStatus.label;
    document.querySelector("[data-goal-preview-status]").className = smartStatus.tone;
    document.querySelector("[data-goal-preview-current]").textContent = brl(current);
    document.querySelector("[data-goal-preview-target]").textContent = brl(target);
    document.querySelector("[data-goal-preview-missing]").textContent = brl(missing);
    document.querySelector("[data-goal-preview-required]").textContent = brl(required);
    document.querySelector("[data-goal-preview-percent]").textContent = `${percent}%`;
    document.querySelector("[data-goal-preview-progress]").style.width = `${percent}%`;
    document.querySelector("[data-goal-preview-progress]").style.background = color;
    document.querySelector("[data-goal-preview-forecast]").textContent = forecast ? shortMonth(forecast) : "-";
    document.querySelector("[data-goal-simulator-monthly]").textContent = brl(boostedPace);
    document.querySelector("[data-goal-simulator-forecast]").textContent = boostedForecast ? shortMonth(boostedForecast) : "-";
    document.querySelector("[data-goal-simulator-delta]").textContent = `${delta} mes(es)`;
    const tip = document.querySelector("[data-goal-preview-tip]");
    if (!target) tip.textContent = "Defina o valor objetivo para ver a simulacao da meta.";
    else if (smartStatus.tone === "success") tip.textContent = "Sua meta esta bem calibrada para o prazo informado.";
    else if (smartStatus.tone === "warning") tip.textContent = `Aumentar o aporte mensal para ${brl(required)} deixa a meta mais confortavel.`;
    else tip.textContent = `Para recuperar o ritmo, tente guardar pelo menos ${brl(required)} por mes.`;
  };

  const openGoalModal = (goal = null) => {
    goalForm.reset();
    goalForm.elements.id.value = goal?.id || "";
    modalTitle.textContent = goal ? "Editar Meta" : "Nova Meta";
    goalForm.elements.color.value = goal?.color || "#8b5cf6";
    goalForm.elements.status.value = goal?.status || "no_ritmo";
    simulatorExtra.value = 0;
    if (goal) {
      ["name", "description", "type", "target_amount", "current_amount", "monthly_target_amount", "start_date", "deadline_date", "icon", "color", "status"].forEach((field) => {
        if (goalForm.elements[field]) goalForm.elements[field].value = goal[field] ?? "";
      });
      goalForm.elements.current_amount.value = goal.current_amount ?? 0;
    }
    setGoalType(goal?.type || "Reserva de emergencia");
    goalFeedback.textContent = "";
    goalModal.hidden = false;
    syncGoalPreview();
  };

  document.querySelectorAll("[data-goal-new]").forEach((button) => {
    button.addEventListener("click", () => openGoalModal());
  });

  document.querySelectorAll("[data-goal-type]").forEach((button) => {
    button.addEventListener("click", () => setGoalType(button.dataset.goalType));
  });

  goalForm.addEventListener("input", syncGoalPreview);
  goalForm.addEventListener("change", (event) => {
    if (event.target.matches("[data-goal-auto-revenue]")) {
      document.querySelector("[data-goal-auto-revenue-options]").hidden = !event.target.checked;
    }
    syncGoalPreview();
  });
  simulatorExtra?.addEventListener("input", syncGoalPreview);

  goalForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(goalForm).entries());
    const id = payload.id;
    delete payload.id;
    const response = await fetch(id ? `/api/goals/${id}` : "/api/goals", {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      goalFeedback.textContent = data.error || "Erro ao salvar meta";
      return;
    }
    window.location.reload();
  });

  contributionForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const goalId = contributionForm.elements.goal_id.value;
    const payload = Object.fromEntries(new FormData(contributionForm).entries());
    const response = await fetch(`/api/goals/${goalId}/contributions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      contributionFeedback.textContent = data.error || "Erro ao salvar contribuicao";
      return;
    }
    window.location.reload();
  });

  document.addEventListener("click", async (event) => {
    const edit = event.target.closest("[data-goal-edit]");
    const contribute = event.target.closest("[data-goal-contribute]");
    const history = event.target.closest("[data-goal-history]");
    const status = event.target.closest("[data-goal-status]");
    const remove = event.target.closest("[data-goal-delete]");

    if (edit) openGoalModal(JSON.parse(edit.dataset.goalEdit));

    if (contribute) {
      contributionForm.reset();
      contributionForm.elements.goal_id.value = contribute.dataset.goalContribute;
      contributionFeedback.textContent = "";
      contributionModal.hidden = false;
    }

    if (history) {
      const response = await fetch(withSelectedPeriod(`/api/goals/${history.dataset.goalHistory}`));
      if (!response.ok) return;
      const data = await response.json();
      const tbody = document.querySelector("[data-goal-history-body]");
      tbody.innerHTML = (data.contributions || [])
        .map((item) => `<tr><td>${item.contribution_date}</td><td>${brl(item.amount)}</td><td>${item.source}</td><td>${item.notes || "-"}</td></tr>`)
        .join("");
      historyModal.hidden = false;
    }

    if (status) {
      const response = await fetch(`/api/goals/${status.dataset.goalStatus}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: status.dataset.status }),
      });
      if (response.ok) window.location.reload();
    }

    if (remove) {
      if (!window.confirm("Excluir esta meta e seu historico de contribuicoes?")) return;
      const response = await fetch(`/api/goals/${remove.dataset.goalDelete}`, { method: "DELETE" });
      if (response.ok) window.location.reload();
    }
  });
}

const transactionsPage = document.querySelector(".transactions-page");

if (transactionsPage) {
  const filtersForm = document.querySelector("[data-transactions-filters]");
  const transactionForm = document.querySelector("[data-transaction-form]");
  const transactionModal = document.getElementById("transaction-modal");
  const modalTitle = document.querySelector("[data-modal-title]");
  const tableBody = document.querySelector("[data-transactions-body]");
  const paginationLabel = document.querySelector("[data-pagination-label]");
  const paginationPages = document.querySelector("[data-pagination-pages]");
  const perPageSelect = document.querySelector("[data-per-page-form] select[name='per_page']");
  let currentPage = 1;

  const brl = (value) =>
    Number(value || 0).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
    });

  const formatDateBR = (value) => {
    if (!value) return "-";
    const [year, month, day] = value.split("-");
    return `${day}/${month}/${year}`;
  };

  const parseBalance = () => Number(transactionsPage.dataset.currentBalance || 0);

  const setTransactionType = (type) => {
    transactionForm.elements.type.value = type;
    if (transactionForm.elements.category_id) transactionForm.elements.category_id.dataset.categoryKind = type === "receita" ? "receita" : "despesa";
    transactionForm.querySelectorAll("[data-type-value]").forEach((button) => {
      button.classList.toggle("active", button.dataset.typeValue === type);
    });
    syncTransactionPreview();
  };

  const syncTransactionPreview = () => {
    const type = transactionForm.elements.type?.value || "despesa";
    const amount = Number(transactionForm.elements.amount?.value || 0);
    const signedImpact = type === "receita" ? amount : -amount;
    const projected = parseBalance() + signedImpact;
    const categorySelect = transactionForm.elements.category_id;
    const category = categorySelect?.selectedOptions?.[0]?.textContent || "Nao selecionada";
    const payment = transactionForm.elements.payment_method?.value || "Nao selecionada";
    const description = transactionForm.elements.description?.value || "Nao informada";
    const status = transactionForm.elements.status?.value || "pago";
    const dateValue = transactionForm.elements.date?.value || selectedPeriodFirstDate();
    const card = document.querySelector("[data-transaction-preview-card]");
    const isIncome = type === "receita";

    if (card) {
      card.classList.toggle("income", isIncome);
      card.classList.toggle("expense", !isIncome);
    }
    document.querySelector("[data-transaction-preview-icon]").textContent = isIncome ? "^" : "v";
    document.querySelector("[data-transaction-preview-type]").textContent = isIncome ? "Receita" : "Despesa";
    document.querySelector("[data-transaction-preview-status]").textContent = status.charAt(0).toUpperCase() + status.slice(1);
    document.querySelector("[data-transaction-preview-amount]").textContent = brl(amount);
    document.querySelector("[data-transaction-preview-date]").textContent = formatDateBR(dateValue);
    document.querySelector("[data-transaction-preview-category]").textContent = category === "Selecione uma categoria" ? "Nao selecionada" : category;
    document.querySelector("[data-transaction-preview-payment]").textContent = payment || "Nao selecionada";
    document.querySelector("[data-transaction-preview-description]").textContent = description;
    document.querySelector("[data-impact-current]").textContent = brl(parseBalance());
    document.querySelector("[data-impact-value]").textContent = `${signedImpact >= 0 ? "+ " : "- "}${brl(Math.abs(signedImpact))}`;
    document.querySelector("[data-impact-value]").className = signedImpact >= 0 ? "receita" : "despesa";
    document.querySelector("[data-impact-projected]").textContent = brl(projected);

    const tip = document.querySelector("[data-transaction-tip]");
    const progress = document.querySelector("[data-tip-progress]");
    const percent = Math.min(Math.round((amount / 500) * 100), 100);
    if (tip) {
      if (!amount) {
        tip.textContent = "Preencha categoria e valor para receber uma dica simples sobre este lancamento.";
      } else if (isIncome) {
        tip.textContent = `Esta receita reforca seu saldo em ${brl(amount)} na competencia selecionada.`;
      } else if (amount > 500) {
        tip.textContent = "Atenção: esta despesa pode impactar sua meta de economia deste mes.";
      } else {
        tip.textContent = `Voce costuma acompanhar esta categoria. Este valor parece controlado para o mes.`;
      }
    }
    if (progress) progress.style.width = `${percent}%`;

    const descCount = document.querySelector("[data-transaction-description-count]");
    if (descCount) descCount.textContent = `${transactionForm.elements.description?.value.length || 0}/120`;
    const notesCount = document.querySelector("[data-transaction-notes-count]");
    if (notesCount) notesCount.textContent = `${transactionForm.elements.notes?.value.length || 0}/200`;

    const recurringOptions = transactionForm.querySelector("[data-transaction-recurring-options]");
    if (recurringOptions) recurringOptions.hidden = !transactionForm.elements.is_recurring?.checked;
    if (transactionForm.elements.recurrence_day && !transactionForm.elements.recurrence_day.value) {
      transactionForm.elements.recurrence_day.value = dateValue.slice(8, 10);
    }
  };

  const filters = () => {
    const data = new FormData(filtersForm);
    if (perPageSelect) data.set("per_page", perPageSelect.value);
    data.set("page", currentPage);
    const params = new URLSearchParams(data);
    selectedPeriodParams().forEach((value, key) => params.set(key, value));
    return params;
  };

  const openTransactionModal = (mode = "create", transaction = null) => {
    transactionForm.reset();
    transactionForm.dataset.mode = mode;
    transactionForm.elements.id.value = transaction?.id || "";
    modalTitle.textContent = mode === "edit" ? "Editar lancamento" : "Novo lancamento";
    if (mode === "create" && transactionForm.elements.date) {
      transactionForm.elements.date.value = selectedPeriodFirstDate();
    }

    if (transaction) {
      ["type", "date", "amount", "category_id", "description", "payment_method", "status", "origin", "fixed_bill_id", "revenue_id", "project_center", "notes", "recurrence_frequency", "recurrence_day", "recurrence_end_date"].forEach((field) => {
        if (transactionForm.elements[field]) transactionForm.elements[field].value = transaction[field] ?? "";
      });
      ["is_recurring", "split_enabled", "reminder_enabled"].forEach((field) => {
        if (transactionForm.elements[field]) transactionForm.elements[field].checked = Boolean(Number(transaction[field] || 0));
      });
    } else {
      if (transactionForm.elements.status) transactionForm.elements.status.value = "pago";
      if (transactionForm.elements.origin) transactionForm.elements.origin.value = "manual";
      if (transactionForm.elements.reminder_enabled) transactionForm.elements.reminder_enabled.checked = true;
    }
    setTransactionType(transactionForm.elements.type.value || "despesa");
    syncTransactionPreview();
    transactionModal.hidden = false;
  };

  const updateSummary = (summary) => {
    const values = {
      receitas: brl(summary.receitas),
      despesas: brl(summary.despesas),
      saldo: brl(summary.saldo),
      total_lancamentos: summary.total_lancamentos,
      media_diaria: brl(summary.media_diaria),
    };

    Object.entries(values).forEach(([key, value]) => {
      document.querySelectorAll(`[data-summary="${key}"], [data-flow="${key}"]`).forEach((element) => {
        element.textContent = value;
      });
    });

    const categoryBars = document.querySelector("[data-category-bars]");
    if (categoryBars) {
      categoryBars.innerHTML = (summary.category_bars || [])
        .map(
          (item) => `
          <div class="category-bar">
            <span><i></i>${item.name}</span>
            <div class="bar-track"><b style="width: ${item.percent}%;"></b></div>
            <strong>${brl(item.total)}</strong>
            <em>${item.percent}%</em>
          </div>`
        )
        .join("");
    }

    const originList = document.querySelector("[data-origin-list]");
    if (originList) {
      originList.innerHTML = (summary.origin_bars || [])
        .map((item) => `<span><i></i>${item.name} <b>${item.percent}%</b></span>`)
        .join("");
    }
  };

  const transactionRow = (item) => {
    const category = item.category_name || "-";
    const description = item.description || "-";
    return `
      <tr data-transaction-id="${item.id}">
        <td>${item.date || ""}</td>
        <td>${item.hour || ""}</td>
        <td>
          <div class="transaction-description">
            <span class="row-icon">${(category || description).slice(0, 1)}</span>
            <div><strong>${description}</strong><small>${item.type || ""}</small></div>
          </div>
        </td>
        <td><em class="badge category-badge">${category}</em></td>
        <td><em class="badge origin-badge">${item.origin || "-"}</em></td>
        <td>${item.payment_method || "-"}</td>
        <td><em class="status ${item.status}">${item.status}</em></td>
        <td class="${item.type}">${brl(item.amount)}</td>
        <td>
          <div class="row-actions">
            <button class="btn-edit-transaction" type="button" title="Editar" data-transaction-id="${item.id}">E</button>
            <button class="btn-duplicate-transaction" type="button" title="Duplicar" data-transaction-id="${item.id}">D</button>
            <button class="btn-delete-transaction" type="button" title="Excluir" data-transaction-id="${item.id}">X</button>
            <button type="button" title="Ver comprovante">P</button>
          </div>
        </td>
      </tr>`;
  };

  const updatePagination = (pagination) => {
    paginationLabel.textContent = `Mostrando ${pagination.start_record} a ${pagination.end_record} de ${pagination.total_records} lancamentos`;
    paginationPages.innerHTML = "";
    for (let page = 1; page <= pagination.total_pages; page += 1) {
      const link = document.createElement("a");
      link.href = "#";
      link.dataset.page = page;
      link.className = page === pagination.page ? "active" : "";
      link.textContent = page;
      paginationPages.appendChild(link);
    }
  };

  const loadTransactions = async () => {
    const params = filters();
    console.log("Filtro aplicado", Object.fromEntries(params.entries()));
    const response = await fetch(`/api/transactions?${params.toString()}`);
    console.log("Resposta API filtros", response.status);
    if (!response.ok) throw new Error("Erro ao carregar lancamentos");
    const data = await response.json();
    tableBody.innerHTML = data.transactions.map(transactionRow).join("");
    updateSummary(data.summary);
    updatePagination(data.pagination);
  };

  document.querySelectorAll(".modal-open").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.modalTarget === "transaction-modal") openTransactionModal("create");
    });
  });

  transactionForm.querySelectorAll("[data-type-value]").forEach((button) => {
    button.addEventListener("click", () => setTransactionType(button.dataset.typeValue));
  });

  transactionForm.addEventListener("input", syncTransactionPreview);
  transactionForm.addEventListener("change", (event) => {
    if (event.target.matches("[data-receipt-input]")) {
      const label = document.querySelector("[data-receipt-file-name]");
      if (label) label.textContent = event.target.files?.[0]?.name || "Adicionar imagem ou PDF";
    }
    syncTransactionPreview();
  });

  filtersForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (event.submitter?.name === "export") {
      const params = filters();
      params.set("export", "csv");
      window.location.href = `/lancamentos?${params.toString()}`;
      return;
    }
    currentPage = 1;
    loadTransactions().catch((error) => console.error("Erro da API", error));
  });

  filtersForm.querySelectorAll("select").forEach((field) => {
    field.addEventListener("change", () => {
      currentPage = 1;
      loadTransactions().catch((error) => console.error("Erro da API", error));
    });
  });

  filtersForm.querySelector("input[name='search']").addEventListener("input", () => {
    window.clearTimeout(filtersForm.searchTimer);
    filtersForm.searchTimer = window.setTimeout(() => {
      currentPage = 1;
      loadTransactions().catch((error) => console.error("Erro da API", error));
    }, 350);
  });

  document.querySelector(".btn-clear-filters").addEventListener("click", () => {
    filtersForm.reset();
    currentPage = 1;
    loadTransactions().catch((error) => console.error("Erro da API", error));
  });

  perPageSelect?.addEventListener("change", () => {
    currentPage = 1;
    loadTransactions().catch((error) => console.error("Erro da API", error));
  });

  paginationPages.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-page]");
    if (!link) return;
    event.preventDefault();
    currentPage = Number(link.dataset.page || 1);
    loadTransactions().catch((error) => console.error("Erro da API", error));
  });

  transactionForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(transactionForm);
    ["is_recurring", "split_enabled", "reminder_enabled"].forEach((field) => {
      formData.set(field, transactionForm.elements[field]?.checked ? "1" : "0");
    });
    const id = formData.get("id");
    formData.delete("id");
    const mode = transactionForm.dataset.mode || "create";
    const url = withSelectedPeriod(mode === "edit" ? `/api/transactions/${id}` : "/api/transactions");
    const method = mode === "edit" ? "PUT" : "POST";
    console.log("Salvando lancamento", { mode, id });
    const response = await fetch(url, {
      method,
      body: formData,
    });
    console.log("Resposta API salvar", response.status);
    if (!response.ok) {
      console.error("Erro da API", await response.text());
      return;
    }
    transactionModal.hidden = true;
    await loadTransactions();
  });

  document.addEventListener("click", async (event) => {
    const editButton = event.target.closest(".btn-edit-transaction");
    const deleteButton = event.target.closest(".btn-delete-transaction");
    const duplicateButton = event.target.closest(".btn-duplicate-transaction");

    if (editButton) {
      const id = editButton.dataset.transactionId;
      console.log("Botao editar clicado", id);
      const response = await fetch(withSelectedPeriod(`/api/transactions/${id}`));
      console.log("Resposta API editar", response.status);
      if (!response.ok) return console.error("Erro da API", await response.text());
      openTransactionModal("edit", await response.json());
    }

    if (deleteButton) {
      const id = deleteButton.dataset.transactionId;
      console.log("Botao excluir clicado", id);
      if (!window.confirm("Tem certeza que deseja excluir este lançamento?")) return;
      const response = await fetch(withSelectedPeriod(`/api/transactions/${id}`), { method: "DELETE" });
      console.log("Resposta API excluir", response.status);
      if (!response.ok) return console.error("Erro da API", await response.text());
      await loadTransactions();
    }

    if (duplicateButton) {
      const id = duplicateButton.dataset.transactionId;
      console.log("Botao duplicar clicado", id);
      const response = await fetch(withSelectedPeriod(`/api/transactions/${id}/duplicate`), { method: "POST" });
      console.log("Resposta API duplicar", response.status);
      if (!response.ok) return console.error("Erro da API", await response.text());
      await loadTransactions();
    }
  });

  window.addEventListener("periodChanged", () => {
    currentPage = 1;
    loadTransactions().catch((error) => console.error("Erro da API", error));
  });
}

const fixedBillsPage = document.querySelector(".fixed-bills-page");

if (fixedBillsPage) {
  const filtersForm = document.querySelector("[data-fixed-bill-filters]");
  const billForm = document.querySelector("[data-fixed-bill-form]");
  const billModal = document.getElementById("fixed-bill-modal");
  const billModalTitle = document.querySelector("[data-bill-modal-title]");
  const billsList = document.querySelector("[data-fixed-bills-list]");
  const installmentToggle = billForm.querySelector("[data-installment-toggle]");
  const installmentOptions = billForm.querySelector("[data-installment-options]");

  const brl = (value) =>
    Number(value || 0).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
    });

  const billFilters = () => {
    const params = new URLSearchParams(new FormData(filtersForm));
    selectedPeriodParams().forEach((value, key) => params.set(key, value));
    return params;
  };

  const setBillCheckbox = (name, checked) => {
    if (billForm.elements[name]) billForm.elements[name].checked = Boolean(Number(checked || 0));
  };

  const selectedText = (fieldName, fallback = "-") => {
    const field = billForm.elements[fieldName];
    if (!field || !field.options) return field?.value || fallback;
    return field.options[field.selectedIndex]?.textContent || fallback;
  };

  const selectedPeriodDate = (day) => {
    const { month, year } = getSelectedPeriod();
    const safeDay = Math.min(Math.max(Number(day || 1), 1), 28);
    return `${year}-${String(month).padStart(2, "0")}-${String(safeDay).padStart(2, "0")}`;
  };

  const monthsBetween = (startDate) => {
    const { month, year } = getSelectedPeriod();
    const parsed = startDate ? new Date(`${startDate}T00:00:00`) : new Date(year, month - 1, 1);
    return (year - parsed.getFullYear()) * 12 + (month - (parsed.getMonth() + 1));
  };

  const updateBillPreview = () => {
    const name = billForm.elements.name?.value || "Nova conta";
    const amount = Number(billForm.elements.default_amount?.value || 0);
    const installmentAmount = Number(billForm.elements.installment_amount?.value || amount);
    const dueDay = billForm.elements.due_day?.value || "--";
    const recurrence = selectedText("recurrence_interval", "Mensal");
    const status = selectedText("status", "Ativa");
    const payment = selectedText("payment_method", "Boleto");
    const isInstallment = installmentToggle?.checked;
    const totalInstallments = Number(billForm.elements.total_installments?.value || 0);
    const paidInstallments = Number(billForm.elements.paid_installments?.value || 0);
    const installmentStart = billForm.elements.installment_start_date?.value || billForm.elements.start_date?.value;
    const currentInstallment = Math.max(1, monthsBetween(installmentStart) + 1);
    const nextInstallment = Math.min(totalInstallments || currentInstallment, Math.max(currentInstallment, paidInstallments + 1));
    const nextAmount = isInstallment ? installmentAmount : amount;

    document.querySelector("[data-bill-preview-name]").textContent = name;
    document.querySelector("[data-bill-preview-status]").textContent = status;
    document.querySelector("[data-bill-preview-amount]").textContent = brl(amount);
    document.querySelector("[data-bill-preview-category]").textContent = selectedText("category_id", "Sem categoria");
    document.querySelector("[data-bill-preview-due]").textContent = `Dia ${dueDay}`;
    document.querySelector("[data-bill-preview-recurrence]").textContent = recurrence;
    document.querySelector("[data-bill-preview-ask]").textContent = billForm.elements.ask_value_before_generate?.checked ? "Sim" : "Nao";
    document.querySelector("[data-bill-preview-update]").textContent = billForm.elements.auto_update_default_value?.checked ? "Sim" : "Nao";
    document.querySelector("[data-bill-preview-payment]").textContent = payment;
    document.querySelector("[data-bill-preview-next-date]").textContent = selectedPeriodDate(dueDay);
    document.querySelector("[data-bill-preview-next-name]").textContent = isInstallment && totalInstallments ? `${name} ${nextInstallment}/${totalInstallments}` : name;
    document.querySelector("[data-bill-preview-next-amount]").textContent = brl(nextAmount);
    document.querySelector("[data-bill-preview-installment]").textContent =
      isInstallment && totalInstallments
        ? `Parcela ${nextInstallment}/${totalInstallments}. Restam ${Math.max(totalInstallments - paidInstallments, 0)} parcela(s).`
        : "Conta recorrente simples.";

    if (billForm.elements.installment_total_amount && isInstallment && totalInstallments && installmentAmount) {
      billForm.elements.installment_total_amount.value = (totalInstallments * installmentAmount).toFixed(2);
    }
  };

  const syncInstallmentVisibility = () => {
    if (!installmentOptions) return;
    installmentOptions.hidden = !installmentToggle?.checked;
    updateBillPreview();
  };

  const openBillModal = (mode = "create", bill = null) => {
    billForm.reset();
    billForm.dataset.mode = mode;
    billForm.elements.id.value = bill?.id || "";
    billModalTitle.textContent = mode === "edit" ? "Editar conta fixa" : "Nova conta fixa";
    if (bill) {
      [
        "name",
        "default_amount",
        "due_day",
        "category_id",
        "status",
        "recurrence_interval",
        "start_date",
        "payment_method",
        "alert_days_before",
        "notes",
        "total_installments",
        "installment_amount",
        "paid_installments",
        "installment_start_date",
        "installment_total_amount",
      ].forEach((field) => {
        if (billForm.elements[field]) billForm.elements[field].value = bill[field] ?? "";
      });
      if (billForm.elements.default_amount && !billForm.elements.default_amount.value) {
        billForm.elements.default_amount.value = bill.expected_amount || "";
      }
      setBillCheckbox("ask_value_before_generate", bill.ask_value_before_generate);
      setBillCheckbox("auto_update_default_value", bill.auto_update_default_value);
      setBillCheckbox("is_installment", bill.is_installment);
    } else {
      billForm.elements.status.value = "ativa";
      billForm.elements.recurrence_interval.value = "mensal";
      billForm.elements.payment_method.value = billForm.elements.payment_method.value || "boleto";
    }
    syncInstallmentVisibility();
    updateBillPreview();
    billModal.hidden = false;
  };

  const updateBillSummary = (summary) => {
    const values = {
      total_mensal: brl(summary.total_mensal),
      contas_pagas: summary.contas_pagas,
      contas_pendentes: summary.contas_pendentes,
      contas_atrasadas: summary.contas_atrasadas,
      contas_adiadas: summary.contas_adiadas,
      proximo_vencimento: summary.proximo_vencimento,
      proximo_valor: brl(summary.proximo_valor),
    };
    Object.entries(values).forEach(([key, value]) => {
      document.querySelectorAll(`[data-bill-summary="${key}"]`).forEach((element) => {
        element.textContent = value;
      });
    });

    const categoryBars = document.querySelector("[data-bill-category-bars]");
    categoryBars.innerHTML = (summary.category_bars || [])
      .map(
        (item) => `
        <div class="category-bar">
          <span><i></i>${item.name}</span>
          <div class="bar-track"><b style="width: ${item.percent}%;"></b></div>
          <strong>${brl(item.total)}</strong>
          <em>${item.percent}%</em>
        </div>`
      )
      .join("");
  };

  const billCard = (bill) => `
    <article class="bill-card priority-${bill.priority_key}" data-bill-id="${bill.id}">
      <div class="bill-card-head">
        <div>
          <strong>${bill.name}</strong>
          <span>${bill.category_name || "Sem categoria"}</span>
        </div>
        <em class="status ${bill.status}">${bill.status}</em>
      </div>
      <div class="bill-card-meta">
        <span>Dia ${bill.due_day}</span>
        <span>${bill.recurrence_interval || bill.recurrence || "mensal"}</span>
        <span>Alerta ${bill.alert_days_before || 0} dia(s)</span>
        ${bill.installment_label ? `<span>Parcela ${bill.installment_label}</span>` : ""}
      </div>
      <strong class="bill-amount">${brl(bill.expected_amount)}</strong>
      <div class="bill-actions">
        <button class="btn-bill-status" type="button" data-bill-id="${bill.id}" data-status="pago">Pagar</button>
        <button class="btn-bill-status" type="button" data-bill-id="${bill.id}" data-status="adiado">Adiar</button>
        <button class="btn-edit-bill" type="button" data-bill-id="${bill.id}">Editar</button>
        <button class="btn-bill-status" type="button" data-bill-id="${bill.id}" data-status="cancelado">Cancelar</button>
        <button class="btn-delete-bill" type="button" data-bill-id="${bill.id}">Excluir</button>
        <button type="button">Historico</button>
      </div>
    </article>`;

  const renderBills = (bills) => {
    const groups = [
      ["atrasadas", "Atrasadas"],
      ["hoje", "Vencem hoje"],
      ["sete_dias", "Proximos 7 dias"],
      ["trinta_dias", "Proximos 30 dias"],
      ["adiadas", "Adiadas"],
      ["pagas", "Pagas"],
    ];
    billsList.innerHTML = groups
      .map(([key, label]) => {
        const items = bills.filter((bill) => bill.priority_key === key);
        if (!items.length) return "";
        return `<section class="bill-group" data-group="${key}"><h3>${label}</h3><div class="bill-card-grid">${items.map(billCard).join("")}</div></section>`;
      })
      .join("");
  };

  const loadBills = async () => {
    const params = billFilters();
    console.log("Filtro de contas aplicado", Object.fromEntries(params.entries()));
    const response = await fetch(`/api/fixed-bills?${params.toString()}`);
    console.log("Resposta API contas", response.status);
    if (!response.ok) throw new Error("Erro ao carregar contas fixas");
    const data = await response.json();
    renderBills(data.bills);
    updateBillSummary(data.summary);
  };

  document.querySelectorAll(".modal-open").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.modalTarget === "fixed-bill-modal") openBillModal("create");
    });
  });

  filtersForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadBills().catch((error) => console.error("Erro da API", error));
  });

  filtersForm.querySelectorAll("select").forEach((field) => {
    field.addEventListener("change", () => loadBills().catch((error) => console.error("Erro da API", error)));
  });

  filtersForm.querySelector("input[name='search']").addEventListener("input", () => {
    window.clearTimeout(filtersForm.searchTimer);
    filtersForm.searchTimer = window.setTimeout(() => loadBills().catch((error) => console.error("Erro da API", error)), 350);
  });

  document.querySelector(".btn-clear-bill-filters").addEventListener("click", () => {
    filtersForm.reset();
    loadBills().catch((error) => console.error("Erro da API", error));
  });

  billForm.addEventListener("input", updateBillPreview);
  billForm.addEventListener("change", (event) => {
    if (event.target.matches("[data-installment-toggle]")) syncInstallmentVisibility();
    if (event.target.matches("[data-bill-receipt-input]")) {
      const label = document.querySelector("[data-bill-receipt-file-name]");
      if (label) label.textContent = event.target.files?.[0]?.name || "Boleto pago, Pix ou debito automatico";
    }
    updateBillPreview();
  });

  billForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(billForm);
    const payload = Object.fromEntries(formData.entries());
    payload.ask_value_before_generate = billForm.elements.ask_value_before_generate?.checked ? "1" : "0";
    payload.auto_update_default_value = billForm.elements.auto_update_default_value?.checked ? "1" : "0";
    payload.is_installment = billForm.elements.is_installment?.checked ? "1" : "0";
    const id = payload.id;
    delete payload.id;
    formData.delete("id");
    Object.entries(payload).forEach(([key, value]) => formData.set(key, value ?? ""));
    const mode = billForm.dataset.mode || "create";
    const url = withSelectedPeriod(mode === "edit" ? `/api/fixed-bills/${id}` : "/api/fixed-bills");
    const method = mode === "edit" ? "PUT" : "POST";
    console.log("Salvando conta fixa", { mode, id, payload });
    const response = await fetch(url, {
      method,
      body: formData,
    });
    console.log("Resposta API salvar conta", response.status);
    if (!response.ok) return console.error("Erro da API", await response.text());
    billModal.hidden = true;
    await loadBills();
  });

  document.addEventListener("click", async (event) => {
    const editButton = event.target.closest(".btn-edit-bill");
    const deleteButton = event.target.closest(".btn-delete-bill");
    const statusButton = event.target.closest(".btn-bill-status");

    if (editButton) {
      const id = editButton.dataset.billId;
      console.log("Editar conta fixa", id);
      const response = await fetch(withSelectedPeriod(`/api/fixed-bills/${id}`));
      console.log("Resposta API editar conta", response.status);
      if (!response.ok) return console.error("Erro da API", await response.text());
      openBillModal("edit", await response.json());
    }

    if (deleteButton) {
      const id = deleteButton.dataset.billId;
      console.log("Excluir conta fixa", id);
      if (!window.confirm("Tem certeza que deseja excluir esta conta fixa?")) return;
      const response = await fetch(withSelectedPeriod(`/api/fixed-bills/${id}`), { method: "DELETE" });
      console.log("Resposta API excluir conta", response.status);
      if (!response.ok) return console.error("Erro da API", await response.text());
      await loadBills();
    }

    if (statusButton) {
      const id = statusButton.dataset.billId;
      const status = statusButton.dataset.status;
      console.log("Alterar status conta fixa", { id, status });
      const response = await fetch(withSelectedPeriod(`/api/fixed-bills/${id}/status`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      console.log("Resposta API status conta", response.status);
      if (!response.ok) return console.error("Erro da API", await response.text());
      await loadBills();
    }
  });

  window.addEventListener("periodChanged", () => {
    loadBills().catch((error) => console.error("Erro da API", error));
  });
}

const revenuesPage = document.querySelector(".revenues-page");

if (revenuesPage) {
  const filtersForm = document.querySelector("[data-revenue-filters]");
  const revenueForm = document.querySelector("[data-revenue-form]");
  const revenueModal = document.getElementById("revenue-modal");
  const revenueModalTitle = document.querySelector("[data-revenue-modal-title]");
  const revenuesBody = document.querySelector("[data-revenues-body]");

  const brl = (value) =>
    Number(value || 0).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
    });

  const formatDateBR = (value) => {
    if (!value) return "-";
    const [year, month, day] = value.split("-");
    return `${day}/${month}/${year}`;
  };

  const addMonths = (value, months) => {
    const date = value ? new Date(`${value}T00:00:00`) : new Date(`${selectedPeriodFirstDate()}T00:00:00`);
    date.setMonth(date.getMonth() + months);
    const day = String(Math.min(date.getDate(), 28)).padStart(2, "0");
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${day}`;
  };

  const nextRevenueDate = () => {
    const base = revenueForm.elements.expected_date?.value || selectedPeriodFirstDate();
    const interval = revenueForm.elements.recurrence_interval?.value || "mensal";
    if (interval === "quinzenal") {
      const date = new Date(`${base}T00:00:00`);
      date.setDate(date.getDate() + 15);
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    }
    if (interval === "semanal") {
      const date = new Date(`${base}T00:00:00`);
      date.setDate(date.getDate() + 7);
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    }
    if (interval === "anual") return addMonths(base, 12);
    return addMonths(base, 1);
  };

  const setCheckbox = (name, value) => {
    if (revenueForm.elements[name]) revenueForm.elements[name].checked = Boolean(Number(value || 0));
  };

  const syncRevenueSmartForm = () => {
    const status = revenueForm.elements.status?.value || "prevista";
    const isReceived = status === "recebida";
    const isRecurring = revenueForm.elements.is_recurring?.checked || revenueForm.elements.type?.value === "recorrente";
    const isSmart = revenueForm.elements.ask_value_before_generate?.checked;
    const receivedField = revenueForm.querySelector(".received-date-field");
    const recurrenceOptions = revenueForm.querySelector("[data-recurring-options]");
    const intelligentSection = revenueForm.querySelector("[data-intelligent-section]");
    const smartPreview = revenueForm.querySelector("[data-smart-preview]");

    if (receivedField) receivedField.hidden = !isReceived;
    if (isReceived && revenueForm.elements.received_date && !revenueForm.elements.received_date.value) {
      revenueForm.elements.received_date.value = new Date().toISOString().slice(0, 10);
    }
    if (!isReceived && revenueForm.elements.received_date) revenueForm.elements.received_date.value = "";

    if (revenueForm.elements.type) revenueForm.elements.type.value = isRecurring ? "recorrente" : "pontual";
    if (recurrenceOptions) recurrenceOptions.hidden = !isRecurring;
    if (intelligentSection) intelligentSection.hidden = !isRecurring;
    if (smartPreview) smartPreview.hidden = !isRecurring || !isSmart;

    if (isRecurring && revenueForm.elements.recurrence_day && !revenueForm.elements.recurrence_day.value) {
      revenueForm.elements.recurrence_day.value = (revenueForm.elements.expected_date?.value || selectedPeriodFirstDate()).slice(8, 10);
    }
    if (isRecurring && revenueForm.elements.recurrence_start_date && !revenueForm.elements.recurrence_start_date.value) {
      revenueForm.elements.recurrence_start_date.value = revenueForm.elements.expected_date?.value || selectedPeriodFirstDate();
    }
    if (revenueForm.elements.next_expected_date) {
      revenueForm.elements.next_expected_date.value = isRecurring ? nextRevenueDate() : "";
    }

    const name = revenueForm.elements.name?.value || "Nova receita";
    const category = revenueForm.elements.category?.value || "Outros";
    const amount = Number(revenueForm.elements.expected_amount?.value || 0);
    const expectedDate = revenueForm.elements.expected_date?.value || selectedPeriodFirstDate();
    const intervalLabel = {
      mensal: `Todo dia ${String(revenueForm.elements.recurrence_day?.value || expectedDate.slice(8, 10)).padStart(2, "0")} de cada mes`,
      quinzenal: "A cada 15 dias",
      semanal: "A cada 7 dias",
      anual: "Uma vez por ano",
    }[revenueForm.elements.recurrence_interval?.value || "mensal"];
    const recurrenceText = isRecurring ? intervalLabel : "Pontual";
    const nextDate = isRecurring ? nextRevenueDate() : "";

    document.querySelector("[data-preview-name]").textContent = name;
    document.querySelector("[data-preview-status]").textContent = status.charAt(0).toUpperCase() + status.slice(1);
    document.querySelector("[data-preview-amount]").textContent = brl(amount);
    document.querySelector("[data-preview-category]").textContent = category;
    document.querySelector("[data-preview-date]").textContent = formatDateBR(expectedDate);
    document.querySelector("[data-preview-recurrence]").textContent = recurrenceText;
    document.querySelector("[data-preview-next-date]").textContent = nextDate ? formatDateBR(nextDate) : "-";
    document.querySelector("[data-preview-next-name]").textContent = name;
    document.querySelector("[data-preview-next-status]").textContent = isRecurring ? "Prevista" : "Pontual";
    document.querySelector("[data-preview-next-amount]").textContent = brl(amount);
    document.querySelector("[data-preview-question]").textContent = `"O valor continua ${brl(amount)}?"`;

    const charCount = document.querySelector("[data-revenue-char-count]");
    if (charCount) charCount.textContent = `${revenueForm.elements.notes?.value.length || 0}/200`;
  };

  const revenueFilters = () => {
    const params = new URLSearchParams(new FormData(filtersForm));
    selectedPeriodParams().forEach((value, key) => params.set(key, value));
    return params;
  };

  const openRevenueModal = (mode = "create", revenue = null) => {
    revenueForm.reset();
    revenueForm.dataset.mode = mode;
    revenueForm.elements.id.value = revenue?.id || "";
    revenueModalTitle.textContent = mode === "edit" ? "Editar receita" : "Nova receita";
    if (mode === "create" && revenueForm.elements.expected_date) {
      revenueForm.elements.expected_date.value = selectedPeriodFirstDate();
      revenueForm.elements.recurrence_start_date.value = selectedPeriodFirstDate();
      revenueForm.elements.recurrence_day.value = selectedPeriodFirstDate().slice(8, 10);
    }
    if (revenue) {
      ["name", "category", "expected_amount", "expected_date", "received_date", "type", "status", "recurrence_interval", "recurrence_day", "recurrence_start_date", "next_expected_date", "last_generated_date", "notes"].forEach((field) => {
        if (revenueForm.elements[field]) revenueForm.elements[field].value = revenue[field] ?? "";
      });
      setCheckbox("is_recurring", revenue.is_recurring);
      setCheckbox("ask_value_before_generate", revenue.ask_value_before_generate);
      setCheckbox("auto_update_default_value", revenue.auto_update_default_value);
      setCheckbox("notify_day_before", revenue.notify_day_before ?? 1);
      setCheckbox("notify_due_day", revenue.notify_due_day ?? 1);
      setCheckbox("notify_overdue", revenue.notify_overdue ?? 1);
      setCheckbox("notify_registered", revenue.notify_registered ?? 1);
    }
    syncRevenueSmartForm();
    revenueModal.hidden = false;
  };

  const updateRevenueSummary = (summary) => {
    const values = {
      receitas_mes: brl(summary.receitas_mes),
      receitas_previstas: brl(summary.receitas_previstas),
      receitas_recebidas: brl(summary.receitas_recebidas),
      receitas_pendentes: brl(summary.receitas_pendentes),
      proximo_nome: summary.proximo_nome,
      proximo_data: summary.proximo_data,
      proximo_valor: brl(summary.proximo_valor),
      percentual_recebido: `${summary.percentual_recebido}%`,
    };
    Object.entries(values).forEach(([key, value]) => {
      document.querySelectorAll(`[data-revenue-summary="${key}"]`).forEach((element) => {
        element.textContent = value;
      });
    });
    const bars = document.querySelector("[data-revenue-category-bars]");
    bars.innerHTML = (summary.category_bars || [])
      .map(
        (item) => `<div class="category-bar"><span><i></i>${item.name}</span><div class="bar-track"><b style="width: ${item.percent}%;"></b></div><strong>${brl(item.total)}</strong><em>${item.percent}%</em></div>`
      )
      .join("");
    const ai = document.querySelector("[data-revenue-ai]");
    if (ai) ai.textContent = `Voce recebeu ${summary.percentual_recebido}% das receitas previstas deste mes.`;
  };

  const revenueRow = (item) => `
    <tr data-revenue-id="${item.id}">
      <td>${item.expected_date || ""}</td>
      <td>${item.received_date || "-"}</td>
      <td><div class="transaction-description"><span class="row-icon">${(item.name || "?").slice(0, 1)}</span><div><strong>${item.name}</strong><small>${item.type}</small></div></div></td>
      <td><em class="badge category-badge">${item.category}</em></td>
      <td><em class="status revenue-status ${item.status}">${item.status}</em></td>
      <td>${item.recurrence}</td>
      <td class="receita">${brl(item.expected_amount)}</td>
      <td><div class="row-actions"><button class="btn-edit-revenue" type="button" data-revenue-id="${item.id}">E</button><button class="btn-receive-revenue" type="button" data-revenue-id="${item.id}">R</button><button class="btn-duplicate-revenue" type="button" data-revenue-id="${item.id}">D</button><button class="btn-delete-revenue" type="button" data-revenue-id="${item.id}">X</button></div></td>
    </tr>`;

  const loadRevenues = async () => {
    const params = revenueFilters();
    console.log("Filtro de receitas aplicado", Object.fromEntries(params.entries()));
    const response = await fetch(`/api/revenues?${params.toString()}`);
    console.log("Resposta API receitas", response.status);
    if (!response.ok) throw new Error("Erro ao carregar receitas");
    const data = await response.json();
    revenuesBody.innerHTML = data.revenues.map(revenueRow).join("");
    updateRevenueSummary(data.summary);
  };

  document.querySelectorAll(".modal-open").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.modalTarget === "revenue-modal") openRevenueModal("create");
    });
  });

  revenueForm.addEventListener("input", (event) => {
    if (event.target.name === "type" && event.target.value === "recorrente" && revenueForm.elements.is_recurring) {
      revenueForm.elements.is_recurring.checked = true;
    }
    syncRevenueSmartForm();
  });

  revenueForm.addEventListener("change", (event) => {
    if (event.target.name === "type" && revenueForm.elements.is_recurring) {
      revenueForm.elements.is_recurring.checked = event.target.value === "recorrente";
    }
    if (event.target.name === "expected_date" && revenueForm.elements.recurrence_start_date) {
      revenueForm.elements.recurrence_start_date.value = event.target.value;
      revenueForm.elements.recurrence_day.value = event.target.value.slice(8, 10);
    }
    if (event.target.matches("[data-revenue-receipt-input]")) {
      const label = document.querySelector("[data-revenue-receipt-file-name]");
      if (label) label.textContent = event.target.files?.[0]?.name || "Pix, deposito, recibo ou transferencia";
    }
    syncRevenueSmartForm();
  });

  filtersForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (event.submitter?.name === "export") {
      const params = revenueFilters();
      params.set("export", "csv");
      window.location.href = `/receitas?${params.toString()}`;
      return;
    }
    loadRevenues().catch((error) => console.error("Erro da API", error));
  });

  filtersForm.querySelectorAll("select").forEach((field) => {
    field.addEventListener("change", () => loadRevenues().catch((error) => console.error("Erro da API", error)));
  });

  filtersForm.querySelector("input[name='search']").addEventListener("input", () => {
    window.clearTimeout(filtersForm.searchTimer);
    filtersForm.searchTimer = window.setTimeout(() => loadRevenues().catch((error) => console.error("Erro da API", error)), 350);
  });

  document.querySelector(".btn-clear-revenue-filters").addEventListener("click", () => {
    filtersForm.reset();
    loadRevenues().catch((error) => console.error("Erro da API", error));
  });

  revenueForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(revenueForm);
    const payload = Object.fromEntries(formData.entries());
    ["is_recurring", "ask_value_before_generate", "auto_update_default_value", "notify_day_before", "notify_due_day", "notify_overdue", "notify_registered"].forEach((field) => {
      payload[field] = revenueForm.elements[field]?.checked ? "1" : "0";
    });
    const id = payload.id;
    delete payload.id;
    formData.delete("id");
    Object.entries(payload).forEach(([key, value]) => formData.set(key, value ?? ""));
    const mode = revenueForm.dataset.mode || "create";
    const response = await fetch(withSelectedPeriod(mode === "edit" ? `/api/revenues/${id}` : "/api/revenues"), {
      method: mode === "edit" ? "PUT" : "POST",
      body: formData,
    });
    console.log("Resposta API salvar receita", response.status);
    if (!response.ok) return console.error("Erro da API", await response.text());
    revenueModal.hidden = true;
    await loadRevenues();
  });

  document.addEventListener("click", async (event) => {
    const editButton = event.target.closest(".btn-edit-revenue");
    const receiveButton = event.target.closest(".btn-receive-revenue");
    const duplicateButton = event.target.closest(".btn-duplicate-revenue");
    const deleteButton = event.target.closest(".btn-delete-revenue");

    if (editButton) {
      const id = editButton.dataset.revenueId;
      const response = await fetch(withSelectedPeriod(`/api/revenues/${id}`));
      if (!response.ok) return console.error("Erro da API", await response.text());
      openRevenueModal("edit", await response.json());
    }

    if (receiveButton) {
      const id = receiveButton.dataset.revenueId;
      const response = await fetch(withSelectedPeriod(`/api/revenues/${id}/status`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "recebida" }),
      });
      if (!response.ok) return console.error("Erro da API", await response.text());
      await loadRevenues();
    }

    if (duplicateButton) {
      const id = duplicateButton.dataset.revenueId;
      const response = await fetch(withSelectedPeriod(`/api/revenues/${id}/duplicate`), { method: "POST" });
      if (!response.ok) return console.error("Erro da API", await response.text());
      await loadRevenues();
    }

    if (deleteButton) {
      const id = deleteButton.dataset.revenueId;
      if (!window.confirm("Tem certeza que deseja excluir esta receita?")) return;
      const response = await fetch(withSelectedPeriod(`/api/revenues/${id}`), { method: "DELETE" });
      if (!response.ok) return console.error("Erro da API", await response.text());
      await loadRevenues();
    }
  });

  window.addEventListener("periodChanged", () => {
    loadRevenues().catch((error) => console.error("Erro da API", error));
  });
}
