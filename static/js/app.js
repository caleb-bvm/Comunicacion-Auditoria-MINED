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

    // Lista de archivos elegidos, en palabras y no con el texto del navegador.
    document.querySelectorAll(".ui-file input[type='file']").forEach((input) => {
        const list = input.closest(".ui-field")?.querySelector("[data-file-list]");
        if (!list) return;
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

    const analysisForm = document.querySelector(".territorial-filter[data-analysis-mode]");
    const periodFilter = analysisForm?.querySelector("[data-period-filter]");
    const periodOptions = periodFilter
        ? Array.from(periodFilter.querySelectorAll('input[name="period"]'))
        : [];
    const customPeriodDates = periodFilter?.querySelector("[data-custom-period-dates]");
    const periodStart = periodFilter?.querySelector("#start");
    const periodEnd = periodFilter?.querySelector("#end");
    const periodSummary = periodFilter?.querySelector("[data-period-summary]");
    const periodError = periodFilter?.querySelector("[data-period-error]");
    const periodServerError = periodFilter?.querySelector(".period-server-error");
    const analysisUpdateStatus = analysisForm?.querySelector(
        "[data-analysis-update-status]"
    );
    const analysisSelects = analysisForm
        ? Array.from(analysisForm.querySelectorAll("select"))
        : [];
    const departmentFilter = analysisForm?.querySelector("#department");
    const districtFilter = analysisForm?.querySelector("#district");
    const advancedAnalysisFilters = analysisForm?.querySelector(
        ".territorial-advanced-filters"
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
    document.querySelectorAll(".analysis-mode-switch a").forEach((link) => {
        link.addEventListener("click", () => {
            persistAnalysisState();
            showAnalysisUpdate();
        });
    });
    updatePeriodFilter();
    restoreAnalysisState();
})();

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
