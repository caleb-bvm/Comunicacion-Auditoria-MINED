(() => {
    document.querySelectorAll("[data-historical-attachments]").forEach((section) => {
        const total = section.querySelector('[name="attachments-TOTAL_FORMS"]');
        const rows = section.querySelector("[data-attachment-rows]");
        const template = section.querySelector("[data-attachment-template]");
        const add = section.querySelector("[data-add-attachment]");
        const limit = section.querySelector("[data-attachment-limit]");
        if (!total || !rows || !template || !add) return;
        const updateLimit = () => {
            const reached = Number(total.value) >= Number(section.dataset.maxForms);
            add.disabled = reached;
            if (limit) limit.hidden = !reached;
        };
        add.addEventListener("click", () => {
            const index = Number(total.value);
            if (index >= Number(section.dataset.maxForms)) return;
            const fragment = template.content.cloneNode(true);
            fragment.querySelectorAll("[name], [id], [for], [aria-describedby]").forEach((element) => {
                ["name", "id", "for", "aria-describedby"].forEach((attribute) => {
                    if (element.hasAttribute(attribute)) {
                        element.setAttribute(attribute, element.getAttribute(attribute).replaceAll("__prefix__", String(index)));
                    }
                });
            });
            rows.append(fragment);
            enhanceFileInputs(rows.lastElementChild || rows);
            total.value = index + 1;
            updateLimit();
            rows.lastElementChild?.querySelector("input, select")?.focus();
        });
        updateLimit();
    });

    const moreTrigger = document.querySelector(".mobile-more-trigger");
    const moreMenu = document.querySelector(".mobile-more-menu");
    const moreScrim = document.querySelector(".mobile-more-scrim");
    const moreClose = document.querySelector(".mobile-more-close");
    const mobileLayout = window.matchMedia("(max-width: 900px)");
    const menuBackground = document.querySelectorAll(".sidebar, .mobile-top-bar, main, .mobile-navigation, .skip-link");

    const setMoreMenu = (open, restoreFocus = true) => {
        if (!moreTrigger || !moreMenu || !moreScrim) return;
        moreTrigger.setAttribute("aria-expanded", String(open));
        moreMenu.hidden = !open;
        moreScrim.hidden = !open;
        document.body.classList.toggle("has-open-mobile-menu", open);
        menuBackground.forEach((element) => { element.inert = open; });
        if (open) {
            moreMenu.scrollTop = 0;
            moreClose?.focus({ preventScroll: true });
        } else if (restoreFocus) moreTrigger.focus({ preventScroll: true });
    };

    moreTrigger?.addEventListener("click", () => {
        setMoreMenu(moreTrigger.getAttribute("aria-expanded") !== "true");
    });
    moreClose?.addEventListener("click", () => setMoreMenu(false));
    moreScrim?.addEventListener("click", () => setMoreMenu(false));
    document.addEventListener("keydown", (event) => {
        if (moreTrigger?.getAttribute("aria-expanded") !== "true") return;
        if (event.key === "Escape") {
            event.preventDefault();
            setMoreMenu(false);
        }
        if (event.key === "Tab") {
            const controls = Array.from(moreMenu.querySelectorAll("a[href], button:not([disabled])"));
            const first = controls[0];
            const last = controls[controls.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first?.focus();
            }
        }
    });
    mobileLayout.addEventListener("change", () => {
        if (!mobileLayout.matches && moreTrigger?.getAttribute("aria-expanded") === "true") {
            setMoreMenu(false, false);
        }
    });
    window.addEventListener("pageshow", () => {
        if (moreTrigger?.getAttribute("aria-expanded") === "true") setMoreMenu(false, false);
    });

    document.querySelectorAll("table[data-mobile-cards]").forEach((table) => {
        // Una columna sin título visible o marcada con data-card-action contiene las acciones de la tarjeta.
        const headings = Array.from(table.querySelectorAll("thead th"), (heading) => (
            heading.hasAttribute("data-card-action") ? "" : heading.textContent.trim()
        ));
        table.querySelectorAll("tbody tr").forEach((row) => {
            Array.from(row.cells).forEach((cell, index) => {
                if (cell.colSpan > 1) {
                    cell.classList.add("mobile-card-message");
                    return;
                }
                cell.dataset.label = headings[index] || "";
                if (!headings[index]) cell.classList.add("mobile-card-action");
                const value = document.createElement("div");
                value.className = "mobile-card-value";
                value.append(...cell.childNodes);
                cell.append(value);
            });
        });
        table.parentElement.classList.add("mobile-card-table");
    });

    const responseForm = document.querySelector("[data-response-form]");
    const conditionalFields = document.querySelectorAll("[data-visible-for-status]");
    const declaredStatus = () => {
        const checked = responseForm?.querySelector('[name="declared_status"]:checked');
        if (checked) return checked.value;
        return responseForm?.querySelector('select[name="declared_status"]')?.value || "";
    };
    const updateResponseFields = () => {
        if (!responseForm || !conditionalFields.length) return;
        const status = declaredStatus();
        conditionalFields.forEach((field) => {
            const visibleFor = (field.dataset.visibleForStatus || "").split(" ");
            const visible = visibleFor.includes(status);
            field.hidden = !visible;
            field.querySelectorAll("input, select, textarea").forEach((control) => {
                control.disabled = !visible;
            });
        });
    };
    responseForm?.addEventListener("change", (event) => {
        if (event.target.name === "declared_status") updateResponseFields();
    });
    updateResponseFields();

    // Formularios por pasos: sin JavaScript todos los pasos se ven a la vez.
    document.querySelectorAll("[data-steps]").forEach((form) => {
        const steps = Array.from(form.querySelectorAll("[data-step]"));
        if (steps.length < 2) return;
        const bars = Array.from(form.querySelectorAll(".ui-steps-bar span"));
        const label = form.querySelector("[data-step-label]");
        let current = steps.findIndex((step) => step.querySelector(".ui-field-error, .errorlist"));
        if (current < 0) current = 0;
        const show = (index, moveFocus) => {
            current = index;
            steps.forEach((step, position) => step.classList.toggle("is-current", position === index));
            bars.forEach((bar, position) => {
                bar.classList.toggle("is-done", position < index);
                bar.classList.toggle("is-current", position === index);
            });
            if (label) label.textContent = `Paso ${index + 1} de ${steps.length}`;
            if (moveFocus) {
                form.scrollIntoView({ block: "start" });
                steps[index].querySelector(".ui-step-title")?.focus({ preventScroll: true });
            }
        };
        const stepIsValid = (step) => {
            const controls = Array.from(step.querySelectorAll("input, select, textarea")).filter(
                (control) => !control.disabled && !control.closest("[hidden]")
            );
            const invalid = controls.find((control) => !control.checkValidity());
            if (invalid) {
                invalid.reportValidity();
                invalid.focus();
                return false;
            }
            return true;
        };
        form.classList.add("ui-steps-enhanced");
        form.querySelectorAll("[data-step-next]").forEach((button) => {
            button.addEventListener("click", () => {
                if (stepIsValid(steps[current])) show(Math.min(current + 1, steps.length - 1), true);
            });
        });
        form.querySelectorAll("[data-step-back]").forEach((button) => {
            button.addEventListener("click", () => show(Math.max(current - 1, 0), true));
        });
        show(current, false);
    });

    enhanceFileInputs(document);
    enhanceOrganizationSearch(document);

    document.querySelectorAll("[data-location-filters]").forEach((form) => {
        const department = form.querySelector('[name="department"]');
        const district = form.querySelector('[name="district"]');
        const municipality = form.querySelector('[name="municipality"]');
        department?.addEventListener("change", () => {
            if (district) district.value = "";
            if (municipality) municipality.value = "";
        });
    });

    document.querySelectorAll("form[data-auto-submit-filters]").forEach((form) => {
        let submitTimer = null;
        let isSubmitting = false;

        const submitFilters = (delay = 0) => {
            if (isSubmitting) return;
            window.clearTimeout(submitTimer);
            submitTimer = window.setTimeout(() => {
                if (form.checkValidity()) form.requestSubmit();
            }, delay);
        };

        form.querySelectorAll("select, input[type='checkbox'], input[type='radio']")
            .forEach((control) => {
                control.addEventListener("change", () => submitFilters(80));
            });
        form.querySelectorAll("input[type='search'], input[type='text'], input:not([type])")
            .forEach((control) => {
                control.setAttribute("enterkeyhint", "search");
                control.addEventListener("input", () => {
                    // Keep the keyboard and partially typed search on phones.
                    if (!mobileLayout.matches) submitFilters(500);
                });
            });
        form.addEventListener("submit", () => {
            isSubmitting = true;
            window.clearTimeout(submitTimer);
        });
    });

    const centerDirectory = document.querySelector("[data-center-directory]");
    const centerViewButtons = Array.from(document.querySelectorAll("[data-center-view]"));
    const centerViewKey = "director-center-directory-view";
    const setCenterView = (view) => {
        if (!centerDirectory || !centerViewButtons.length) return;
        const compact = view === "compact";
        centerDirectory.classList.toggle("is-compact", compact);
        centerViewButtons.forEach((button) => {
            const active = button.dataset.centerView === view;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", String(active));
        });
        try {
            localStorage.setItem(centerViewKey, view);
        } catch (_error) {
            // The view still works when local storage is unavailable.
        }
    };
    if (centerDirectory && centerViewButtons.length) {
        let savedCenterView = "cards";
        try {
            savedCenterView = localStorage.getItem(centerViewKey) || "cards";
        } catch (_error) {
            savedCenterView = "cards";
        }
        setCenterView(savedCenterView === "compact" ? "compact" : "cards");
        centerViewButtons.forEach((button) => {
            button.addEventListener("click", () => setCenterView(button.dataset.centerView));
        });
    }

    const suspensionDialog = document.querySelector("[data-suspend-dialog]");
    const suspensionForm = suspensionDialog?.querySelector("[data-suspend-form]");
    const suspensionName = suspensionDialog?.querySelector("[data-suspend-account-name]");
    document.querySelectorAll("[data-suspend-account]").forEach((button) => {
        button.addEventListener("click", () => {
            if (!suspensionDialog || !suspensionForm || !suspensionName) return;
            suspensionForm.action = button.dataset.action;
            suspensionName.textContent = button.dataset.accountName || "esta institución";
            suspensionDialog.showModal();
            suspensionDialog.querySelector("textarea")?.focus();
        });
    });
    suspensionDialog?.querySelectorAll("[data-close-dialog]").forEach((button) => {
        button.addEventListener("click", () => suspensionDialog.close());
    });
    suspensionDialog?.addEventListener("click", (event) => {
        if (event.target === suspensionDialog) suspensionDialog.close();
    });

    const analysisForm = document.querySelector("form[data-analysis-mode]");
    const periodFilter = analysisForm?.querySelector("[data-period-filter]");
    const periodOptions = periodFilter
        ? Array.from(periodFilter.querySelectorAll('input[name="period"]'))
        : [];
    const customPeriodDates = periodFilter?.querySelector("[data-custom-period-dates]");
    const periodStart = periodFilter?.querySelector("#start");
    const periodEnd = periodFilter?.querySelector("#end");
    const periodSummary = periodFilter?.querySelector("[data-period-summary]");
    const periodError = periodFilter?.querySelector("[data-period-error]");
    const periodServerError = periodFilter?.querySelector("[data-period-server-error]");
    const analysisUpdateStatus = analysisForm?.querySelector(
        "[data-analysis-update-status]"
    );
    const analysisSelects = analysisForm
        ? Array.from(analysisForm.querySelectorAll("select"))
        : [];
    const departmentFilter = analysisForm?.querySelector("#department");
    const districtFilter = analysisForm?.querySelector("#district");
    const advancedAnalysisFilters = analysisForm?.querySelector(
        "[data-advanced-filters]"
    );
    const analysisStateKey = "director-analysis-filter-state";
    let analysisSubmitTimer = null;
    let analysisIsSubmitting = false;
    let analysisPeriodIsValid = true;

    const formatPeriodDate = (value) => {
        if (!value) return "";
        const [year, month, day] = value.split("-");
        return `${day}/${month}/${year}`;
    };

    const updatePeriodFilter = ({ userInteraction = false } = {}) => {
        if (
            !analysisForm ||
            !periodFilter ||
            !customPeriodDates ||
            !periodStart ||
            !periodEnd ||
            !periodSummary ||
            !periodError
        ) return;

        const selectedPeriod = periodOptions.find((option) => option.checked);
        if (!selectedPeriod) return;

        const isActivityMode = analysisForm.dataset.analysisMode === "activity";
        const isCustomPeriod = selectedPeriod.value === "custom";
        customPeriodDates.hidden = !isCustomPeriod;
        periodStart.disabled = !isCustomPeriod;
        periodEnd.disabled = !isCustomPeriod;
        periodStart.required = isActivityMode && isCustomPeriod;
        periodEnd.required = isActivityMode && isCustomPeriod;

        let errorMessage = "";
        if (isCustomPeriod && (!periodStart.value || !periodEnd.value)) {
            errorMessage = "Indica una fecha inicial y una fecha final.";
            periodSummary.textContent = "Completa las dos fechas para aplicar el rango.";
        } else if (isCustomPeriod && periodStart.value > periodEnd.value) {
            errorMessage = "La fecha inicial no puede ser posterior a la fecha final.";
            periodSummary.textContent = "Corrige el orden de las fechas para continuar.";
        } else if (isCustomPeriod) {
            periodSummary.textContent = `Mostrando actividad del ${formatPeriodDate(periodStart.value)} al ${formatPeriodDate(periodEnd.value)}`;
        } else if (selectedPeriod.value === "all") {
            periodSummary.textContent = "Mostrando actividad de todo el historial";
        } else {
            periodSummary.textContent = `Mostrando actividad: ${selectedPeriod.dataset.periodLabel}`;
        }

        periodError.textContent = errorMessage;
        periodError.hidden =
            !errorMessage || (!userInteraction && Boolean(periodServerError));
        periodStart.setAttribute("aria-invalid", String(Boolean(errorMessage)));
        periodEnd.setAttribute("aria-invalid", String(Boolean(errorMessage)));
        analysisPeriodIsValid = !isActivityMode || !errorMessage;
        if (userInteraction && periodServerError) periodServerError.hidden = true;
    };

    const persistAnalysisState = () => {
        if (!analysisForm) return;
        try {
            sessionStorage.setItem(
                analysisStateKey,
                JSON.stringify({
                    path: window.location.pathname,
                    scrollX: window.scrollX,
                    scrollY: window.scrollY,
                    focusId: document.activeElement?.id || "",
                    advancedOpen: Boolean(advancedAnalysisFilters?.open),
                })
            );
        } catch (_error) {
            // The filters still work if session storage is unavailable.
        }
    };

    const showAnalysisUpdate = () => {
        if (!analysisForm || !analysisUpdateStatus) return;
        analysisForm.classList.add("is-updating");
        analysisForm.setAttribute("aria-busy", "true");
        analysisUpdateStatus.hidden = false;
    };

    const submitAnalysisFilters = (delay = 0) => {
        if (!analysisForm || analysisIsSubmitting) return;
        window.clearTimeout(analysisSubmitTimer);
        analysisSubmitTimer = window.setTimeout(() => {
            if (!analysisPeriodIsValid || !analysisForm.checkValidity()) return;
            analysisForm.requestSubmit();
        }, delay);
    };

    const restoreAnalysisState = () => {
        if (!analysisForm) return;
        let savedState = null;
        try {
            savedState = JSON.parse(sessionStorage.getItem(analysisStateKey));
            sessionStorage.removeItem(analysisStateKey);
        } catch (_error) {
            return;
        }
        if (!savedState || savedState.path !== window.location.pathname) return;
        if (advancedAnalysisFilters && savedState.advancedOpen) {
            advancedAnalysisFilters.open = true;
        }
        window.requestAnimationFrame(() => {
            window.scrollTo(savedState.scrollX || 0, savedState.scrollY || 0);
            if (savedState.focusId) {
                document.getElementById(savedState.focusId)?.focus({ preventScroll: true });
            }
        });
    };

    periodOptions.forEach((option) => {
        option.addEventListener("change", () => {
            updatePeriodFilter({ userInteraction: true });
            if (option.value !== "custom") submitAnalysisFilters(80);
        });
    });
    [periodStart, periodEnd].forEach((dateField) => {
        dateField?.addEventListener("input", () => {
            updatePeriodFilter({ userInteraction: true });
            if (periodError?.hidden) submitAnalysisFilters(450);
        });
    });
    analysisSelects.forEach((select) => {
        select.addEventListener("change", () => {
            if (select === departmentFilter) {
                if (districtFilter) districtFilter.value = "";
            }
            submitAnalysisFilters(80);
        });
    });
    analysisForm?.addEventListener("submit", () => {
        analysisIsSubmitting = true;
        persistAnalysisState();
        showAnalysisUpdate();
    });
    document.querySelectorAll("[data-analysis-mode-switch] a").forEach((link) => {
        link.addEventListener("click", () => {
            persistAnalysisState();
            showAnalysisUpdate();
        });
    });
    updatePeriodFilter();
    restoreAnalysisState();
})();

// Accesos rápidos de fecha (plazos en días hábiles calculados en el servidor).
document.querySelectorAll("[data-fill-date]").forEach((button) => {
    const input = document.getElementById(button.dataset.fillDate);
    if (!input) return;
    const group = Array.from(document.querySelectorAll(`[data-fill-date="${button.dataset.fillDate}"]`));
    const refresh = () => group.forEach((item) => {
        item.setAttribute("aria-pressed", String(item.dataset.value === input.value));
    });
    button.addEventListener("click", () => {
        input.value = button.dataset.value;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        refresh();
    });
    input.addEventListener("change", refresh);
    refresh();
});

// Frases frecuentes: "insert" agrega la frase en el cursor; "line" agrega o quita una línea propia.
// Se usa delegación para que funcione también en filas agregadas después a un formset.
(() => {
    const refresh = (field) => {
        const current = field.value.split(/\r?\n/).map((line) => line.trim());
        document.querySelectorAll(`[data-insert-into="${field.id}"][data-insert-mode="line"]`).forEach((button) => {
            button.setAttribute("aria-pressed", String(current.includes(button.dataset.text)));
        });
    };
    const insertAtCursor = (field, text) => {
        const focused = document.activeElement === field;
        const start = focused ? field.selectionStart : field.value.length;
        const end = focused ? field.selectionEnd : field.value.length;
        const before = field.value.slice(0, start);
        const after = field.value.slice(end);
        const lead = before && !/\s$/.test(before) ? " " : "";
        field.value = before + lead + text + after;
        const caret = (before + lead + text).length;
        field.focus();
        field.setSelectionRange(caret, caret);
    };
    const toggleLine = (field, text) => {
        const current = field.value.split(/\r?\n/);
        const index = current.findIndex((line) => line.trim() === text);
        if (index >= 0) {
            current.splice(index, 1);
            field.value = current.join("\n").replace(/^\n+|\n+$/g, "");
        } else {
            field.value = field.value.trim() ? `${field.value.replace(/\s+$/, "")}\n${text}` : text;
        }
    };
    // Conserva el cursor del campo: el clic en el chip no le quita el foco.
    document.addEventListener("mousedown", (event) => {
        if (event.target.closest("[data-insert-into]")) event.preventDefault();
    });
    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-insert-into]");
        const field = button && document.getElementById(button.dataset.insertInto);
        if (!field) return;
        if (button.dataset.insertMode === "line") toggleLine(field, button.dataset.text);
        else insertAtCursor(field, button.dataset.text);
        field.dispatchEvent(new Event("input", { bubbles: true }));
    });
    document.addEventListener("input", (event) => {
        if (event.target.id && document.querySelector(`[data-insert-into="${event.target.id}"]`)) refresh(event.target);
    });
    new Set(Array.from(document.querySelectorAll("[data-insert-into]"), (button) => button.dataset.insertInto))
        .forEach((id) => { const field = document.getElementById(id); if (field) refresh(field); });
})();

// Formsets con filas agregables: <section data-formset="prefijo"> con [data-formset-rows],
// <template data-formset-template> (empty_form) y un botón [data-formset-add].
document.querySelectorAll("[data-formset]").forEach((section) => {
    const prefix = section.dataset.formset;
    const total = section.querySelector(`[name="${prefix}-TOTAL_FORMS"]`);
    const rows = section.querySelector("[data-formset-rows]");
    const template = section.querySelector("[data-formset-template]");
    const add = section.querySelector("[data-formset-add]");
    if (!total || !rows || !template || !add) return;
    const attributes = ["name", "id", "for", "aria-describedby", "aria-labelledby", "data-insert-into"];
    add.addEventListener("click", () => {
        const index = Number(total.value);
        const fragment = template.content.cloneNode(true);
        fragment.querySelectorAll("*").forEach((element) => {
            attributes.forEach((attribute) => {
                if (element.hasAttribute(attribute)) {
                    element.setAttribute(attribute, element.getAttribute(attribute).replaceAll("__prefix__", String(index)));
                }
            });
        });
        fragment.querySelectorAll("[data-formset-number]").forEach((element) => {
            element.textContent = String(index + 1);
        });
        const numberInput = fragment.querySelector(`[name="${prefix}-${index}-number"]`);
        if (numberInput && !numberInput.value) numberInput.value = String(index + 1);
        rows.append(fragment);
        total.value = index + 1;
        rows.lastElementChild?.querySelector("textarea")?.focus();
    });
});

// Confirmaciones y alcance de envío sin manejadores en línea (la CSP los bloquea).
document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
});
document.querySelectorAll("[data-set-scope]").forEach((button) => {
    button.addEventListener("click", () => {
        const scope = button.form?.querySelector('[name="scope"]');
        if (scope) scope.value = button.dataset.setScope;
    });
});

document.querySelectorAll("[data-select-page]").forEach((toggle) => {
    const group = toggle.dataset.selectPage;
    const items = Array.from(document.querySelectorAll(`[data-selection-item="${group}"]`));
    const refresh = () => {
        const checked = items.filter((item) => item.checked).length;
        toggle.checked = items.length > 0 && checked === items.length;
        toggle.indeterminate = checked > 0 && checked < items.length;
    };
    toggle.addEventListener("change", () => {
        // El evento actualiza también los otros controles del mismo grupo (cabecera y barra móvil),
        // incluido este, por lo que el valor se guarda antes de recorrer los elementos.
        const checked = toggle.checked;
        items.forEach((item) => {
            item.checked = checked;
            item.dispatchEvent(new Event("change"));
        });
        refresh();
    });
    items.forEach((item) => item.addEventListener("change", refresh));
    refresh();
});

// Mostrar u ocultar la contraseña: el botón solo aparece si hay JavaScript.
document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    const input = document.getElementById(button.dataset.passwordToggle);
    const label = button.querySelector("[data-password-toggle-label]");
    if (!input) return;
    button.hidden = false;
    button.addEventListener("click", () => {
        const visible = input.type === "password";
        input.type = visible ? "text" : "password";
        button.setAttribute("aria-pressed", String(visible));
        if (label) label.textContent = visible ? "Ocultar" : "Mostrar";
    });
});

// Selector de archivos en palabras: reemplaza el texto del navegador («Choose File»)
// por una zona con el nombre y tamaño de lo elegido. Sin JavaScript queda el control nativo.
function enhanceFileInputs(root) {
    root.querySelectorAll("input[type='file']").forEach((input) => {
        if (input.dataset.fileEnhanced || input.closest(".bulk-dropzone, [data-native-file]")) return;
        input.dataset.fileEnhanced = "true";
        let zone = input.closest(".ui-file");
        if (!zone) {
            zone = document.createElement("div");
            zone.className = "ui-file";
            input.before(zone);
            zone.append(input);
            const label = document.createElement("span");
            label.className = "ui-file-zone";
            label.setAttribute("aria-hidden", "true");
            label.innerHTML = '<svg class="ui-icon" focusable="false"><use href="#ui-upload"></use></svg>';
            label.append(input.multiple ? "Elegir archivos" : "Elegir archivo");
            zone.append(label);
        }
        let list = zone.parentElement.querySelector("[data-file-list]");
        if (!list) {
            list = document.createElement("ul");
            list.className = "ui-file-list";
            list.dataset.fileList = "";
            list.setAttribute("aria-label", "Archivos elegidos");
            zone.after(list);
        }
        input.addEventListener("change", () => {
            list.replaceChildren(
                ...Array.from(input.files).map((file) => {
                    const item = document.createElement("li");
                    const size = file.size >= 1048576 ? `${(file.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`;
                    item.textContent = `${file.name} · ${size}`;
                    return item;
                })
            );
        });
    });
}

// Buscador de organizaciones: el <select> llega solo con la opción elegida y aquí se
// convierte en un cuadro de búsqueda (patrón combobox de ARIA) que consulta el catálogo.
function enhanceOrganizationSearch(root) {
    root.querySelectorAll("select[data-org-search]").forEach((select, instance) => {
        if (select.dataset.orgSearchEnhanced || select.disabled) return;
        select.dataset.orgSearchEnhanced = "true";
        const wrapper = document.createElement("div");
        wrapper.className = "ui-org-search";
        const input = document.createElement("input");
        const listbox = document.createElement("ul");
        const status = document.createElement("p");
        const baseId = select.id || `org-search-${instance}`;
        input.type = "text";
        input.id = baseId;
        input.autocomplete = "off";
        input.spellcheck = false;
        input.placeholder = "Escriba el código o el nombre";
        input.required = select.required;
        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");
        input.setAttribute("aria-controls", `${baseId}-results`);
        ["aria-describedby", "aria-invalid"].forEach((attribute) => {
            if (select.hasAttribute(attribute)) input.setAttribute(attribute, select.getAttribute(attribute));
        });
        listbox.id = `${baseId}-results`;
        listbox.className = "ui-org-search-results";
        listbox.setAttribute("role", "listbox");
        listbox.hidden = true;
        status.className = "ui-help ui-org-search-status";
        status.setAttribute("role", "status");
        select.id = `${baseId}-select`;
        select.required = false;
        select.hidden = true;
        select.tabIndex = -1;
        select.before(wrapper);
        wrapper.append(input, listbox, status, select);

        const chosen = select.selectedOptions[0];
        if (chosen && chosen.value) input.value = chosen.textContent.trim();
        const emptyOption = Array.from(select.options).find((option) => option.value === "");
        let results = [];
        let active = -1;
        let timer;
        let controller;

        const setStatus = (text) => { status.textContent = text; };
        const close = () => {
            listbox.hidden = true;
            input.setAttribute("aria-expanded", "false");
            input.removeAttribute("aria-activedescendant");
            active = -1;
        };
        const highlight = (index) => {
            active = index;
            Array.from(listbox.children).forEach((item, position) => {
                item.setAttribute("aria-selected", String(position === index));
                if (position === index) {
                    input.setAttribute("aria-activedescendant", item.id);
                    item.scrollIntoView({ block: "nearest" });
                }
            });
        };
        const setValue = (result) => {
            const options = emptyOption ? [emptyOption] : [];
            if (result) options.push(new Option(result.text, result.id, true, true));
            select.replaceChildren(...options);
            select.value = result ? String(result.id) : "";
            select.dispatchEvent(new Event("change", { bubbles: true }));
        };
        const choose = (result) => {
            setValue(result);
            input.value = result.text;
            input.setCustomValidity("");
            setStatus("");
            close();
        };
        const render = (more) => {
            listbox.replaceChildren(...results.map((result, index) => {
                const item = document.createElement("li");
                item.id = `${baseId}-option-${index}`;
                item.className = "ui-org-search-option";
                item.setAttribute("role", "option");
                item.setAttribute("aria-selected", "false");
                item.textContent = result.text;
                // mousedown evita que el campo pierda el foco antes de elegir.
                item.addEventListener("mousedown", (event) => {
                    event.preventDefault();
                    choose(result);
                });
                return item;
            }));
            const open = results.length > 0;
            listbox.hidden = !open;
            input.setAttribute("aria-expanded", String(open));
            active = -1;
            if (!results.length) setStatus("No se encontraron organizaciones con ese texto.");
            else if (more) setStatus(`Se muestran los primeros ${results.length} resultados; escriba más para precisar.`);
            else setStatus(results.length === 1 ? "1 resultado." : `${results.length} resultados.`);
        };
        const search = async (term) => {
            controller?.abort();
            controller = new AbortController();
            const url = new URL(select.dataset.orgSearch, window.location.origin);
            url.searchParams.set("q", term);
            setStatus("Buscando…");
            try {
                const response = await fetch(url, {
                    headers: { Accept: "application/json" },
                    signal: controller.signal,
                });
                if (!response.ok) throw new Error(String(response.status));
                const data = await response.json();
                results = data.results;
                render(data.more);
            } catch (error) {
                if (error.name === "AbortError") return;
                results = [];
                close();
                setStatus("No se pudo consultar el catálogo. Intente de nuevo.");
            }
        };

        input.addEventListener("input", () => {
            if (select.value) setValue(null);
            const term = input.value.trim();
            input.setCustomValidity(term ? "Elija una organización de la lista de resultados." : "");
            clearTimeout(timer);
            if (term.replace(/\s+/g, "").length < 2) {
                controller?.abort();
                results = [];
                close();
                setStatus(term ? "Escriba al menos 2 caracteres." : "");
                return;
            }
            timer = setTimeout(() => search(term), 200);
        });
        input.addEventListener("keydown", (event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                if (!results.length) return;
                event.preventDefault();
                if (listbox.hidden) {
                    listbox.hidden = false;
                    input.setAttribute("aria-expanded", "true");
                }
                const step = event.key === "ArrowDown" ? 1 : -1;
                highlight((active + step + results.length) % results.length);
            } else if (event.key === "Enter" && !listbox.hidden) {
                event.preventDefault();
                if (active >= 0) choose(results[active]);
                else if (results.length === 1) choose(results[0]);
            } else if (event.key === "Escape" && !listbox.hidden) {
                event.preventDefault();
                close();
            }
        });
        input.addEventListener("blur", close);
    });
}
