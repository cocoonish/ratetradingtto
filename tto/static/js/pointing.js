// Excel's pointing while a formula is typed - into a calc sheet's cell (calc.js) or a page's input cell (grid.js): a click
// on a cell puts its reference in where a reference may go.

/** A workbook cell ("C & R!B5" of the book "tto") as a formula names it: 'C & R'!B5, [sofr]SOFR_FOMC!B9. */
export function workbookRef(book, ref) {
  const k = ref.lastIndexOf('!');
  const sheet = ref.slice(0, k);
  const name = book && book !== 'tto' ? '[' + book + ']' + sheet : sheet;
  const plain = /^[A-Za-z_][A-Za-z0-9_.]*$/.test(sheet) && !/^[A-Za-z]{1,3}\d+$/.test(sheet);
  return (plain ? name : "'" + name.replace(/'/g, "''") + "'") + '!' + ref.slice(k + 1);
}

/** Whether the caret of a formula's editor stands where a reference may go (after =, an operator, a bracket or a separator). */
export function canPoint(input) {
  const before = input.value.slice(0, input.selectionStart).replace(/\s+$/, '');
  return before.startsWith('=') && /[=(,;+\-*/^&<>:]$/.test(before);
}

export const isFormula = (s) => typeof s === 'string' && s.trimStart().startsWith('=');
