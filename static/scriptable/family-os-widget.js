// Family OS – Widget für die iOS-App „Scriptable“ (A-12).
// Zeigt heute und morgen: Bringen, Abholen, Nanny, Abendessen, Tage ohne
// Krippe sowie deine offenen Aufgaben und Abstimmungen. Liest nur; der
// Schlüssel lässt sich in Family OS unter „Verbindungen“ jederzeit widerrufen.
// Größen: klein, mittel, groß. Antippen öffnet Family OS.

const ORIGIN = '__FOS_ORIGIN__';
const KEY = '__FOS_KEY__';

const files = FileManager.local();
const cachePath = files.joinPath(files.documentsDirectory(), 'family-os-widget.json');

const colors = {
  text: Color.dynamic(new Color('#17212b'), new Color('#eef2f5')),
  muted: Color.dynamic(new Color('#5b6873'), new Color('#9aa7b1')),
  accent: Color.dynamic(new Color('#1c6b4f'), new Color('#5cc79c')),
  warn: Color.dynamic(new Color('#9a5b00'), new Color('#f0b35a')),
  background: Color.dynamic(new Color('#f4f6f3'), new Color('#141b21')),
};

async function load() {
  const request = new Request(ORIGIN + '/api/widget');
  request.headers = {Authorization: 'Bearer ' + KEY};
  request.timeoutInterval = 10;
  try {
    const data = await request.loadJSON();
    const status = request.response.statusCode;
    if (status === 401) return {error: 'Widget-Schlüssel ungültig. In Family OS neu erstellen.'};
    if (status !== 200) throw new Error('HTTP ' + status);
    files.writeString(cachePath, JSON.stringify(data));
    return {data};
  } catch (error) {
    // Offline: show the last known state, clearly marked as old.
    if (files.fileExists(cachePath)) {
      return {data: JSON.parse(files.readString(cachePath)), stale: true};
    }
    return {error: 'Keine Verbindung zu Family OS.'};
  }
}

function localDay(offset) {
  const date = new Date(Date.now() + offset * 86400000);
  const pad = number => String(number).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// "Heute"/"Morgen" only while the data is current; old data shows the date.
function dayTitle(day) {
  if (day.day === localDay(0)) return 'Heute';
  if (day.day === localDay(1)) return 'Morgen';
  return day.day.slice(8, 10) + '.' + day.day.slice(5, 7) + '.';
}

function stamp(iso) {
  const time = iso.slice(11, 16);
  return iso.slice(0, 10) === localDay(0) ? time : `${iso.slice(8, 10)}.${iso.slice(5, 7)}. ${time}`;
}

function symbol(name) {
  // Older iOS versions lack some symbols; fall back to a plain dot.
  return (SFSymbol.named(name) || SFSymbol.named('circle.fill')).image;
}

function addLine(stack, name, text, color, size) {
  const row = stack.addStack();
  row.centerAlignContent();
  const image = row.addImage(symbol(name));
  image.imageSize = new Size(size, size);
  image.tintColor = color || colors.muted;
  row.addSpacer(5);
  const label = row.addText(text);
  label.font = Font.systemFont(size);
  label.textColor = color || colors.text;
  label.lineLimit = 1;
  label.minimumScaleFactor = 0.8;
  return row;
}

function addDay(stack, day, compact) {
  const title = dayTitle(day);
  const size = compact ? 12 : 13;
  const head = stack.addText(title);
  head.font = Font.boldSystemFont(size);
  head.textColor = colors.accent;
  if (day.closure) {
    addLine(stack, 'house', day.closure, colors.warn, size);
  } else if (day.bring || day.pickup) {
    if (compact) {
      addLine(stack, 'figure.and.child.holdinghands', `${day.bring || '–'} → ${day.pickup || '–'}`, null, size);
    } else {
      addLine(stack, 'sunrise', 'Bringen: ' + (day.bring || '–'), null, size);
      addLine(stack, 'sunset', 'Abholen: ' + (day.pickup || '–'), null, size);
    }
  } else {
    addLine(stack, 'moon.zzz', 'Keine Krippe', null, size);
  }
  if (day.nanny.length) addLine(stack, 'person.2', 'Nanny ' + day.nanny.join(', '), null, size);
  if (day.dinner && !compact) addLine(stack, 'fork.knife', day.dinner, null, size);
}

function addOpen(stack, data, compact) {
  const parts = [];
  if (data.approvals) parts.push(`${data.approvals} zu bestätigen`);
  if (data.tasks) parts.push(`${data.tasks} ${data.tasks === 1 ? 'Aufgabe' : 'Aufgaben'}`);
  if (data.issues && !compact) parts.push(`${data.issues} Klärung`);
  const color = data.approvals ? colors.warn : null;
  addLine(stack, parts.length ? 'checklist' : 'checkmark.circle', parts.join(' · ') || 'Nichts offen', color, compact ? 12 : 13);
}

function build(result) {
  const family = config.widgetFamily || 'medium';
  const widget = new ListWidget();
  widget.backgroundColor = colors.background;
  widget.url = ORIGIN + '/';
  widget.setPadding(12, 14, 12, 14);
  widget.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);

  if (result.error) {
    addLine(widget, 'exclamationmark.triangle', 'Family OS', colors.warn, 13);
    widget.addSpacer(6);
    const text = widget.addText(result.error);
    text.font = Font.systemFont(12);
    text.textColor = colors.text;
    return widget;
  }

  const data = result.data;
  const [today, tomorrow] = data.days;
  if (family === 'small') {
    addDay(widget, today, true);
    widget.addSpacer();
    addOpen(widget, data, true);
  } else {
    const columns = widget.addStack();
    const left = columns.addStack();
    left.layoutVertically();
    addDay(left, today, false);
    columns.addSpacer(12);
    const right = columns.addStack();
    right.layoutVertically();
    addDay(right, tomorrow, false);
    widget.addSpacer();
    addOpen(widget, data, false);
    if (family === 'large') {
      for (const title of data.task_titles) addLine(widget, 'circle', title, null, 12);
    }
  }

  widget.addSpacer(4);
  const footer = widget.addText((result.stale ? 'Offline · Stand ' : 'Stand ') + stamp(data.generated));
  footer.font = Font.systemFont(9);
  footer.textColor = result.stale ? colors.warn : colors.muted;
  return widget;
}

const widget = build(await load());
if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  await widget.presentMedium();
}
Script.complete();
