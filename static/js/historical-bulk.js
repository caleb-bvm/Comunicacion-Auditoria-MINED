(() => {
    'use strict';
    const configElement = document.getElementById('historical-bulk-config');
    if (!configElement) return;
    const config = JSON.parse(configElement.textContent);
    const $ = (id) => document.getElementById(id);
    const rows = [];
    let nextId = 0, running = false, pause = false;
    const finished = (row) => ['saved', 'duplicate'].includes(row.status);
    const notice = (message) => { $('bulk-notice').textContent = message; };
    function options(select, choices, placeholder) {
        const value = select.value;
        select.replaceChildren(new Option(placeholder, ''));
        choices.forEach(([key, label]) => select.add(new Option(label, key)));
        if ([...select.options].some((option) => option.value === value)) select.value = value;
    }
    options($('bulk-type'), config.types, 'Sin cambiar');
    options($('bulk-visibility'), config.visibilities, 'Sin cambiar');
    function reportChoices(exclude) {
        return [
            ...config.reports.map((report) => [`existing:${report.id}`, `${report.reference || 'Sin referencia'} · ${report.title}`]),
            ...rows.filter((row) => row !== exclude && row.type.value === 'historical_report')
                .map((row) => [`new:${row.id}`, `Del lote: ${row.title.value || row.file.name}`]),
        ];
    }
    function refreshReports() {
        options($('bulk-report'), reportChoices(), 'Sin cambiar');
        rows.forEach((row) => {
            options(row.parent, reportChoices(row), 'Seleccione un informe');
            row.parent.disabled = finished(row) || row.type.value === 'historical_report';
        });
    }
    function refresh() {
        const done = rows.filter(finished).length;
        const duplicates = rows.filter((row) => row.status === 'duplicate').length;
        const errors = rows.filter((row) => row.status === 'error').length;
        $('bulk-empty').hidden = rows.length > 0;
        $('bulk-save').disabled = running || rows.length === done;
        $('bulk-save').textContent = errors ? 'Reintentar pendientes y errores' : 'Guardar pendientes';
        $('bulk-editor').disabled = running;
        $('bulk-pause').hidden = !running;
        $('bulk-progress').max = rows.length || 1;
        $('bulk-progress').value = done;
        $('bulk-summary').textContent = `${rows.length} archivos · ${done - duplicates} guardados · ${duplicates} duplicados · ${errors} con error · ${rows.length - done - errors} pendientes`;
        rows.forEach((row) => row.tr.querySelectorAll('input, select, button').forEach((control) => {
            control.disabled = finished(row) || (control === row.parent && row.type.value === 'historical_report');
        }));
    }
    function makeInput(tag, attributes, label) {
        const element = document.createElement(tag);
        Object.entries(attributes).forEach(([name, value]) => { element[name] = value; });
        element.setAttribute('aria-label', label);
        return element;
    }
    function addFiles(files) {
        if (running) return;
        if (rows.length + files.length > config.maxFiles) {
            notice(`El lote admite ${config.maxFiles} archivos. Seleccione menos archivos o termine este lote primero.`);
            return;
        }
        for (const file of files) {
            const row = {id: ++nextId, file, status: 'pending'};
            row.tr = document.createElement('tr');
            const cell = (...children) => {
                const td = document.createElement('td'); td.append(...children); row.tr.append(td);
            };
            row.selected = makeInput('input', {type: 'checkbox', checked: true}, `Seleccionar ${file.name}`);
            cell(row.selected);
            const filename = document.createElement('strong'); filename.textContent = file.name;
            const size = document.createElement('small'); size.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB`;
            row.title = makeInput('input', {type: 'text', maxLength: 300, value: file.name.replace(/\.[^.]+$/, '')}, `Descripción de ${file.name}`);
            row.reference = makeInput('input', {type: 'text', maxLength: 80, placeholder: 'Referencia (opcional)'}, `Referencia de ${file.name}`);
            cell(filename, size, row.title, row.reference);
            row.type = makeInput('select', {}, `Tipo de ${file.name}`);
            config.types.forEach(([key, label]) => row.type.add(new Option(label, key)));
            row.type.value = 'other'; cell(row.type);
            row.parent = makeInput('select', {}, `Informe de ${file.name}`); cell(row.parent);
            row.date = makeInput('input', {type: 'date'}, `Fecha original de ${file.name}`);
            row.visibility = makeInput('select', {}, `Visibilidad de ${file.name}`);
            config.visibilities.forEach(([key, label]) => row.visibility.add(new Option(label, key)));
            row.visibility.value = 'audit_only'; cell(row.date, row.visibility);
            row.result = document.createElement('span'); row.result.textContent = 'Pendiente'; cell(row.result);
            const remove = makeInput('button', {type: 'button', textContent: 'Quitar', className: 'button button-secondary'}, `Quitar ${file.name}`);
            remove.addEventListener('click', () => {
                rows.splice(rows.indexOf(row), 1); row.tr.remove(); refreshReports(); refresh();
            });
            cell(remove);
            row.type.addEventListener('change', refreshReports);
            row.title.addEventListener('change', refreshReports);
            rows.push(row); $('bulk-rows').append(row.tr);
            refreshReports();
            if (config.selectedReport) row.parent.value = `existing:${config.selectedReport}`;
        }
        notice('Revise el tipo y el informe de cada archivo antes de guardar.');
        refresh();
    }
    $('bulk-files').addEventListener('change', (event) => { addFiles([...event.target.files]); event.target.value = ''; });
    ['dragover', 'drop'].forEach((name) => $('bulk-dropzone').addEventListener(name, (event) => {
        event.preventDefault();
        if (name === 'drop') addFiles([...event.dataTransfer.files]);
    }));
    $('bulk-select-all').addEventListener('change', (event) => rows.filter((row) => !finished(row)).forEach((row) => { row.selected.checked = event.target.checked; }));
    $('bulk-apply').addEventListener('click', () => {
        const selected = rows.filter((row) => !finished(row) && row.selected.checked);
        selected.forEach((row) => {
            if ($('bulk-type').value) row.type.value = $('bulk-type').value;
            if ($('bulk-date').value) row.date.value = $('bulk-date').value;
            if ($('bulk-visibility').value) row.visibility.value = $('bulk-visibility').value;
        });
        const parentValue = $('bulk-report').value;
        refreshReports();
        selected.forEach((row) => {
            if (parentValue && row.type.value !== 'historical_report') row.parent.value = parentValue;
        });
        notice(selected.length ? `Se actualizaron ${selected.length} filas. Revise los cambios antes de guardar.` : 'Seleccione al menos una fila.');
    });
    function send(row, parentId) {
        return new Promise((resolve, reject) => {
            const body = new FormData();
            body.append('csrfmiddlewaretoken', $('historical-bulk-form').querySelector('[name=csrfmiddlewaretoken]').value);
            body.append('file', row.file);
            Object.entries({document_type: row.type.value, title: row.title.value, reference: row.reference.value,
                document_date: row.date.value, visibility: row.visibility.value, parent_report: parentId || ''})
                .forEach(([key, value]) => body.append(key, value));
            const xhr = new XMLHttpRequest();
            xhr.open('POST', config.url); xhr.timeout = 120000;
            xhr.upload.onprogress = (event) => {
                if (event.lengthComputable) {
                    const percent = Math.round(event.loaded / event.total * 100);
                    row.result.textContent = percent === 100 ? 'Guardando…' : `Subiendo ${percent}%`;
                }
            };
            xhr.onload = () => {
                let data;
                try { data = JSON.parse(xhr.responseText); }
                catch { reject(new Error('No se pudo completar la carga. Revise su sesión y reintente.')); return; }
                if (xhr.status >= 200 && xhr.status < 300 && ['saved', 'duplicate'].includes(data.status)) resolve(data);
                else reject(new Error(data.error || 'No se pudo completar la carga. Revise su sesión y reintente.'));
            };
            xhr.onerror = xhr.ontimeout = () => reject(new Error('La conexión se interrumpió. Reintente; si ya se guardó, se reconocerá como duplicado.'));
            xhr.send(body);
        });
    }
    $('bulk-pause').addEventListener('click', () => { pause = true; $('bulk-pause').disabled = true; });
    $('historical-bulk-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        if (running) return;
        running = true; pause = false; $('bulk-pause').disabled = false; refresh();
        // Parents must exist before uploading their children, regardless of row order.
        const queue = rows.filter((row) => !finished(row)).sort((a, b) =>
            Number(b.type.value === 'historical_report') - Number(a.type.value === 'historical_report'));
        try {
            for (const row of queue) {
                if (pause) break;
                row.result.replaceChildren();
                try {
                    if (row.file.size > config.maxMB * 1024 * 1024) throw new Error(`El archivo supera ${config.maxMB} MB.`);
                    if (!row.date.validity.valid) throw new Error('Revise la fecha original.');
                    let parentId = '';
                    if (row.type.value !== 'historical_report') {
                        const [kind, id] = row.parent.value.split(':');
                        if (kind === 'existing') parentId = id;
                        else if (kind === 'new') {
                            const parent = rows.find((item) => String(item.id) === id);
                            if (!parent || !finished(parent)) throw new Error('Primero debe guardarse el informe seleccionado. Corrija el informe y reintente.');
                            parentId = parent.reportId;
                        }
                        if (!parentId) throw new Error('Seleccione el informe al que pertenece este documento.');
                    }
                    row.result.textContent = 'Subiendo…';
                    const data = await send(row, parentId);
                    row.status = data.status; row.reportId = data.report_id;
                    row.result.textContent = data.message;
                    const link = document.createElement('a'); link.href = data.url; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Ver informe';
                    row.result.append(document.createElement('br'), link);
                } catch (error) {
                    row.status = 'error'; row.result.textContent = error.message;
                }
                row.tr.dataset.status = row.status; refresh();
            }
        } finally {
            running = false; refresh();
            notice(pause ? 'Carga pausada. Puede continuar con los pendientes.' : 'Carga terminada. Revise el resultado de cada archivo.');
        }
    });
    window.addEventListener('beforeunload', (event) => {
        if (running || rows.some((row) => !finished(row))) { event.preventDefault(); event.returnValue = ''; }
    });
    refreshReports(); refresh();
})();
