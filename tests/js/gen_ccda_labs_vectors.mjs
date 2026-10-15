#!/usr/bin/env node
// Writes tests/data/ccda_labs_vectors.json: what js/engine/ccda_labs.js (Lab results → "Import from a patient portal file", a C-CDA
// health summary read on the device) answers for each case below. The reader has no Python twin (the XML is parsed in the browser; the
// server only sees the rows the person keeps), so the file pins its behaviour. Every case carries a `want` that is written BY HAND here
// (the counts that are not zero, the rows newest first, a part of each refusal's words): this script stops when the module disagrees, so
// the pinned answers are not just a copy of what the module said. All documents are invented (made-up names, ids and values; no real
// person's data). tests/test_ccda_labs.py checks every converted value against app/units.py and sends every importable row to
// POST /api/labs/import; node tests/js/run_vectors.mjs replays the cases. The XML is parsed here by tests/js/mini_xml.mjs (a browser
// has DOMParser; Node has no XML parser and the repo takes no dependency); tools/e2e/regress.py runs a real sample through Chromium.
//
//   node tests/js/gen_ccda_labs_vectors.mjs
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
import vm from 'node:vm';
import { parse } from './mini_xml.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const ENGINE = ['rules', 'kidney_function', 'fhir_labs', 'ccda_labs'].map((p) => `app/static/js/engine/${p}.js`);
const OUT = join(ROOT, 'tests', 'data', 'ccda_labs_vectors.json');

const context = vm.createContext({ console });
for (const rel of ENGINE) vm.runInContext(readFileSync(join(ROOT, rel), 'utf8'), context, { filename: rel });
const FL = vm.runInContext('globalThis.KH.fhirLabs', context);
const C = vm.runInContext('globalThis.KH.ccdaLabs', context);
const plain = (v) => JSON.parse(JSON.stringify(v));

const TODAY = '2026-10-15';
const opts = (extra = {}) => ({ today: TODAY, tzOffsetMinutes: 0, ...extra });

// ---- hand-written documents --------------------------------------------------------------------------------------------------
const LOINC = '2.16.840.1.113883.6.1';
const SNOMED = '2.16.840.1.113883.6.96';
const RESULTS_REQUIRED = '2.16.840.1.113883.10.20.22.2.3.1';
const RESULTS_OPTIONAL = '2.16.840.1.113883.10.20.22.2.3';
const RESULT_ORGANIZER = '2.16.840.1.113883.10.20.22.4.1';
const RESULT_OBSERVATION = '2.16.840.1.113883.10.20.22.4.2';
const template = (oid, extension) => `<templateId root="${oid}"${extension ? ` extension="${extension}"` : ''}/>`;
const NS = 'xmlns="urn:hl7-org:v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:sdtc="urn:hl7-org:sdtc"';

// The people in a document carry a made-up name and id on purpose: the reader never looks at them, so they appear in no answer.
const HEADER = `<realmCode code="US"/><typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>${template('2.16.840.1.113883.10.20.22.1.1', '2015-08-01')}`
  + '<id root="1.3.6.1.4.1.99999.1" extension="example-0001"/><code code="34133-9" codeSystem="2.16.840.1.113883.6.1" displayName="Summarization of Episode Note"/>'
  + '<title>Health Summary</title><effectiveTime value="20261014120000-0500"/>'
  + '<recordTarget><patientRole><id root="1.3.6.1.4.1.99999.1" extension="example-0001"/><addr><streetAddressLine>1 Example Street</streetAddressLine><city>Exampleville</city></addr>'
  + '<telecom value="tel:+1-555-0100"/><patient><name><given>Sam</given><family>Example</family></name><birthTime value="19700101"/></patient></patientRole></recordTarget>'
  + '<author><time value="20261014"/><assignedAuthor><id root="1.3.6.1.4.1.99999.2" extension="example-0002"/><assignedPerson><name><given>Dr</given><family>Example</family></name></assignedPerson></assignedAuthor></author>';
const PERFORMER = '<performer typeCode="PRF"><assignedEntity><id root="1.3.6.1.4.1.99999.2" extension="example-0002"/><assignedPerson><name><given>Dr</given><family>Example</family></name></assignedPerson></assignedEntity></performer>';

let serial = 0;
// One Result Observation. `o` replaces a part: templates, code, status, time, value, after (more elements at the end).
function obs(code, value, unit, date, o = {}) {
  serial += 1;
  return `<observation classCode="OBS" moodCode="EVN">${o.templates ?? template(RESULT_OBSERVATION, '2015-08-01') + template(RESULT_OBSERVATION)}`
    + `<id root="1.3.6.1.4.1.99999.3" extension="example-obs-${serial}"/>`
    + `${o.code ?? `<code code="${code}" codeSystem="${LOINC}" displayName="test ${code}"/>`}`
    + `${o.status ?? '<statusCode code="completed"/>'}${o.time ?? `<effectiveTime value="${date}"/>`}`
    + `${o.value ?? `<value xsi:type="PQ" value="${value}" unit="${unit}"/>`}${PERFORMER}${o.after ?? ''}</observation>`;
}
const component = (inner) => `<component>${inner}</component>`;
const organizer = (...inner) => `<entry typeCode="DRIV"><organizer classCode="BATTERY" moodCode="EVN">${template(RESULT_ORGANIZER, '2015-08-01')}${template(RESULT_ORGANIZER)}`
  + `<id root="1.3.6.1.4.1.99999.4" extension="example-org"/><code code="24323-8" codeSystem="${LOINC}" displayName="Comprehensive metabolic 2000 panel"/>`
  + `<statusCode code="completed"/><effectiveTime><low value="20260301"/></effectiveTime>${inner.map(component).join('')}</organizer></entry>`;
const entry = (inner) => `<entry typeCode="DRIV">${inner}</entry>`;
const NARRATIVE = '<text><table><thead><tr><th>Test</th><th>Result</th></tr></thead><tbody><tr><td>Potassium</td><td>4.1 mmol/L</td></tr></tbody></table></text>';
const section = (templates, content, title = 'Results') => `<section>${templates}<code code="30954-2" codeSystem="${LOINC}" displayName="Relevant diagnostic tests and/or laboratory data"/><title>${title}</title>${NARRATIVE}${content}</section>`;
const REQUIRED = template(RESULTS_REQUIRED, '2015-08-01') + template(RESULTS_REQUIRED);
const results = (...entries) => component(section(REQUIRED, entries.join('')));
const ccda = (...sections) => `<?xml version="1.0" encoding="UTF-8"?>\n<?xml-stylesheet type="text/xsl" href="CDA.xsl"?>\n<ClinicalDocument ${NS}>${HEADER}`
  + `<component><structuredBody>${sections.join('')}</structuredBody></component></ClinicalDocument>`;
const labs = (...observations) => ccda(results(organizer(...observations)));
const file = (name, text) => ({ name, text });

// Every code in the table: [value as the lab printed it, the UCUM unit].
const SAMPLE = {
  '2823-3': [4.6, 'mmol/L'], '77142-8': [4.8, 'mmol/L'], '2777-1': [4.1, 'mg/dL'], '14879-1': [1.3, 'mmol/L'], '1751-7': [3.9, 'g/dL'],
  '61151-7': [4.0, 'g/dL'], '61152-5': [3.7, 'g/dL'], '77148-5': [38, 'g/L'], '1963-8': [23, 'mmol/L'], '2028-9': [24, 'meq/L'],
  '9318-7': [24, 'ug/mg{creat}'], '14959-1': [18, 'mg/g{creat}'], '32294-1': [2.1, 'mg/mmol{creat}'], '30000-4': [3.4, 'mg/mmol{creat}'],
  '2160-0': [1.7, 'mg/dL'], '14682-9': [150, 'umol/L'], '77140-2': [162, 'umol/L'], '33863-2': [1.45, 'mg/L'],
  '98979-8': [41, 'mL/min/{1.73_m2}'], '98980-6': [44, 'mL/min/{1.73_m2}'], '62238-1': [52, 'mL/min/{1.73_m2}'], '94677-2': [47, 'mL/min/{1.73_m2}'],
  '50210-4': [49, 'mL/min/1.73m2'], '4548-4': [7.1, '%'], '17856-6': [6.8, '%'], '4549-2': [53, 'mmol/mol'],
};
const addDays = (compact, n) => new Date(Date.parse(`${compact.slice(0, 4)}-${compact.slice(4, 6)}-${compact.slice(6, 8)}T00:00:00Z`) + n * 86400000).toISOString().slice(0, 10).replace(/-/g, '');
const everyCode = FL.LOINC_LIST.map(([, code], i) => obs(code, SAMPLE[code][0], SAMPLE[code][1], addDays('20260301', i * 3)));

const K_CODE = (code, system = LOINC) => `<code code="${code}" codeSystem="${system}"/>`;

const CASES = [
  // ---- the table ------------------------------------------------------------------------------------------------------------
  ['every code in the table, in one Results section, with the UCUM unit LOINC gives', [file('HealthSummary.xml', labs(...everyCode))], opts(), {
    counts: { files: 1, read: 1, observations: 26, found: 26 },
    rowCount: 26,
    firstRows: ['2026-05-15 a1c 53 mmol/mol = 7.0 %', '2026-05-12 a1c 6.8 %', '2026-05-09 a1c 7.1 %'],
  }],
  ['units written in the several ways real exports use all reach the same canonical value', [file('HealthSummary.xml', labs(
    obs('2160-0', 1.7, 'mg/dL', '20260901'), obs('14682-9', 150.28, 'umol/L', '20260902'), obs('2777-1', 3.9, 'mg/dL', '20260903'),
    obs('14879-1', 1.3, 'mmol/L', '20260904'), obs('4548-4', 53, 'mmol/mol', '20260905'), obs('1751-7', 40, 'g/L', '20260906'),
    obs('9318-7', 3.4, 'mg/mmol{creat}', '20260907'), obs('2823-3', 4.7, 'meq/L', '20260908'), obs('62238-1', 38, 'mL/min/{1.73_m2}', '20260909'),
    obs('50210-4', 39, 'mL/min/1.73m2', '20260910'), obs('9318-7', 24, 'ug/mg{creat}', '20260911'), obs('2160-0', 1.8, ' mg/dL ', '20260912'),
  ))], opts(), {
    counts: { files: 1, read: 1, observations: 12, found: 12 },
    rows: [
      '2026-09-12 creatinine 1.80 mg/dL', '2026-09-11 uacr 24.0 mg/g', '2026-09-10 egfr 39 mL/min/1.73 m²', '2026-09-09 egfr 38 mL/min/1.73 m²',
      '2026-09-08 potassium 4.7 mEq/L = 4.7 mmol/L', '2026-09-07 uacr 3.4 mg/mmol = 30.1 mg/g', '2026-09-06 albumin 40 g/L = 4.0 g/dL',
      '2026-09-05 a1c 53 mmol/mol = 7.0 %', '2026-09-04 phosphate 1.3 mmol/L = 4.0 mg/dL', '2026-09-03 phosphate 3.9 mg/dL',
      '2026-09-02 creatinine 150.28 µmol/L = 1.70 mg/dL', '2026-09-01 creatinine 1.70 mg/dL',
    ],
  }],
  // ---- sections and entries -------------------------------------------------------------------------------------------------
  ['organizers, observations directly in an entry, and both Results section templates (entries required and optional)', [
    file('required.xml', ccda(results(
      organizer(obs('2823-3', 4.5, 'mmol/L', '20260901'), obs('2160-0', 1.7, 'mg/dL', '20260901')),
      organizer(obs('2777-1', 3.9, 'mg/dL', '20260902')),
      entry(obs('2823-3', 4.6, 'mmol/L', '20260903')),
    ))),
    file('optional.xml', ccda(component(section(template(RESULTS_OPTIONAL, '2015-08-01') + template(RESULTS_OPTIONAL), entry(obs('1751-7', 3.8, 'g/dL', '20260904')) + organizer(obs('1963-8', 24, 'mmol/L', '20260905')))))),
    file('both.xml', ccda(component(section(template(RESULTS_OPTIONAL) + template(RESULTS_REQUIRED), organizer(obs('33863-2', 1.5, 'mg/L', '20260906')))))), // as in the HL7 example
    file('nested.xml', ccda(component(`<section><templateId root="2.16.840.1.113883.10.20.22.2.5.1"/><title>Problems</title>${component(section(REQUIRED, organizer(obs('4548-4', 6.9, '%', '20260907'))))}</section>`))),
    file('two-sections.xml', ccda(results(organizer(obs('2823-3', 5.1, 'mmol/L', '20260908'))), results(organizer(obs('2823-3', 5.2, 'mmol/L', '20260909'))))),
  ], opts(), {
    counts: { files: 5, read: 5, observations: 10, found: 10 },
    rows: [
      '2026-09-09 potassium 5.2 mmol/L', '2026-09-08 potassium 5.1 mmol/L', '2026-09-07 a1c 6.9 %', '2026-09-06 cystatin_c 1.50 mg/L', '2026-09-05 bicarbonate 24.0 mmol/L',
      '2026-09-04 albumin 3.8 g/dL', '2026-09-03 potassium 4.6 mmol/L', '2026-09-02 phosphate 3.9 mg/dL', '2026-09-01 potassium 4.5 mmol/L', '2026-09-01 creatinine 1.70 mg/dL',
    ],
  }],
  ['a section that is not a Results section is ignored, and so is everything in an observation that is not a Result Observation', [
    file('vitals.xml', ccda(
      component(section(template('2.16.840.1.113883.10.20.22.2.4.1', '2015-08-01'), organizer(obs('2823-3', 4.4, 'mmol/L', '20260901')), 'Vital signs')), // a lab code, but in the wrong section
      component(section(template('2.16.840.1.113883.10.20.22.2.5.1'), entry(obs('2160-0', 1.6, 'mg/dL', '20260901')), 'Problems')),
      component('<section><title>Plan of care</title><text>Potassium 4.1 mmol/L</text></section>'),
    )),
    file('no-templates.xml', ccda(component(section('', organizer(obs('2823-3', 4.4, 'mmol/L', '20260902')))))), // the template is what makes it Results
    file('other-templates.xml', ccda(results(
      organizer(obs('2823-3', 4.3, 'mmol/L', '20260903', { templates: template('2.16.840.1.113883.10.20.22.4.27', '2014-06-09') })), // a vital sign observation
      organizer(obs('2823-3', 4.2, 'mmol/L', '20260904', { templates: '' })),
      entry(`<act classCode="ACT" moodCode="EVN"><code nullFlavor="NA"/>${component(obs('2823-3', 4.1, 'mmol/L', '20260905'))}</act>`), // an act is not followed
      organizer(obs('2823-3', 4.0, 'mmol/L', '20260906', { after: `<entryRelationship typeCode="COMP">${obs('2160-0', 1.9, 'mg/dL', '20260906')}</entryRelationship>` })),
    ))),
    file('no-results.xml', ccda(component(section(template('2.16.840.1.113883.10.20.22.2.6.1'), '', 'Allergies')))),
  ], opts(), {
    counts: { files: 4, read: 4, observations: 1, notLab: 2, noResults: 3, found: 1 },
    rows: ['2026-09-06 potassium 4.0 mmol/L'],
  }],
  // ---- codes ----------------------------------------------------------------------------------------------------------------
  ['LOINC translation codes: a local code with a LOINC translation is read, a translation of another system or another test is not', [file('HealthSummary.xml', labs(
    obs('', 4.1, 'mmol/L', '20260901', { code: `<code code="LAB-K" codeSystem="1.3.6.1.4.1.99999.5"><translation code="2823-3" codeSystem="${LOINC}"/></code>` }), // the real shape: code/translation
    obs('', 4.2, 'mmol/L', '20260902', { code: `<code nullFlavor="OTH"><translation code="2823-3" codeSystem="${LOINC}"/></code>` }),
    obs('', 4.3, 'mmol/L', '20260903', { code: `<code code="LAB-K" codeSystem="1.3.6.1.4.1.99999.5"><translation code="2823-3" codeSystem="${SNOMED}"/></code>` }),
    obs('', 4.4, 'mmol/L', '20260904', { code: `<code code="2823-3" codeSystem="${LOINC}"><translation code="77142-8" codeSystem="${LOINC}"/></code>` }), // two LOINC codes, one test
    obs('', 4.5, 'mmol/L', '20260905', { code: `<code code="2823-3" codeSystem="${LOINC}"><translation code="2160-0" codeSystem="${LOINC}"/></code>` }), // two tests: not guessed
    obs('', 4.6, 'mmol/L', '20260906', { code: `<code code="LAB-K" codeSystem="1.3.6.1.4.1.99999.5"><originalText>Potassium</originalText><translation code="LOCAL" codeSystem="1.3.6.1.4.1.99999.6"/><translation code="2823-3" codeSystem="${LOINC}"/></code>` }),
  ))], opts(), {
    counts: { files: 1, read: 1, observations: 6, unknownCode: 2, found: 4 },
    rows: ['2026-09-06 potassium 4.6 mmol/L', '2026-09-04 potassium 4.4 mmol/L', '2026-09-02 potassium 4.2 mmol/L', '2026-09-01 potassium 4.1 mmol/L'],
  }],
  ['an observation that is not a lab test (a blood pressure, an unknown LOINC code, the wrong code system) is skipped and counted', [file('HealthSummary.xml', labs(
    obs('85354-9', 128, 'mm[Hg]', '20260901'),
    obs('24323-8', 1, 'x', '20260901'), // a comprehensive metabolic panel: a group, not one test
    obs('2828-2', 40, 'mmol/L', '20260901'), // potassium in URINE
    obs('2161-8', 120, 'mg/dL', '20260901'), // creatinine in URINE
    obs('6298-4', 6.1, 'mmol/L', '20260901'), // whole blood: not read
    obs('48642-3', 60, 'mL/min/{1.73_m2}', '20260901'), // race-specific MDRD: not read
    obs('2345-7', 99, 'mg/dL', '20260901'),
    obs('', 4.6, 'mmol/L', '20260901', { code: K_CODE('2823-3', SNOMED) }), // the same number in the SNOMED CT code system
    obs('', 4.6, 'mmol/L', '20260901', { code: '<code code="2823-3"/>' }), // no code system
    obs('', 4.6, 'mmol/L', '20260901', { code: '<code code="2823-3" codeSystem="LOINC"/>' }), // a name, not the OID
    obs('', 4.6, 'mmol/L', '20260901', { code: '' }),
    obs('', 4.6, 'mmol/L', '20260901', { code: '<code/>' }),
  ))], opts(), { counts: { files: 1, read: 1, observations: 12, unknownCode: 12 }, rows: [] }],
  ['only completed results are read', [file('HealthSummary.xml', labs(
    obs('2823-3', 4.5, 'mmol/L', '20260901'),
    obs('2823-3', 4.6, 'mmol/L', '20260902', { status: '<statusCode code="completed"/>' }),
    obs('2823-3', 4.7, 'mmol/L', '20260903', { status: '<statusCode code=" completed "/>' }),
    obs('2823-3', 4.8, 'mmol/L', '20260904', { status: '<statusCode code="active"/>' }), // pending
    obs('2823-3', 4.9, 'mmol/L', '20260905', { status: '<statusCode code="aborted"/>' }),
    obs('2823-3', 5.0, 'mmol/L', '20260906', { status: '<statusCode code="cancelled"/>' }),
    obs('2823-3', 5.1, 'mmol/L', '20260907', { status: '<statusCode code="held"/>' }),
    obs('2823-3', 5.2, 'mmol/L', '20260908', { status: '<statusCode code="suspended"/>' }),
    obs('2823-3', 5.3, 'mmol/L', '20260909', { status: '<statusCode code="COMPLETED"/>' }),
    obs('2823-3', 5.4, 'mmol/L', '20260910', { status: '<statusCode/>' }),
    obs('2823-3', 5.5, 'mmol/L', '20260911', { status: '<statusCode nullFlavor="NI"/>' }),
    obs('2823-3', 5.6, 'mmol/L', '20260912', { status: '' }),
  ))], opts(), {
    counts: { files: 1, read: 1, observations: 12, wrongStatus: 9, found: 3 },
    rows: ['2026-09-03 potassium 4.7 mmol/L', '2026-09-02 potassium 4.6 mmol/L', '2026-09-01 potassium 4.5 mmol/L'],
  }],
  // ---- the value and its unit ------------------------------------------------------------------------------------------------
  ['a unit the app does not know for that test, or no unit, is refused and counted, never guessed', [file('HealthSummary.xml', labs(
    obs('2823-3', 18, 'mg/dL', '20260901'),
    obs('2160-0', 12, 'mg/L', '20260901'),
    obs('2823-3', 4.5, '', '20260901', { value: '<value xsi:type="PQ" value="4.5"/>' }),
    obs('2823-3', 4.5, '', '20260902'),
    obs('2823-3', 4.5, '1', '20260902'), // the HL7 default unit: dimensionless
    obs('98979-8', 60, 'mL/min', '20260901'),
    obs('2823-3', 4.5, 'x'.repeat(200), '20260901'),
    obs('2823-3', 4.5, 'mmol/L', '20260904'),
  ))], opts(), {
    counts: { files: 1, read: 1, observations: 8, badUnit: 7, found: 1 },
    rows: ['2026-09-04 potassium 4.5 mmol/L'],
    problemsInclude: ['the app cannot convert the unit “mg/dL” for Potassium', 'the app cannot convert the unit “mg/L” for Creatinine (blood)', 'no unit is given',
      'the app cannot convert the unit “1” for Potassium', 'the app cannot convert the unit “mL/min” for eGFR (reported by the lab)', 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx…'],
  }],
  ['a value that is not a single number is listed, never turned into one', [file('HealthSummary.xml', labs(
    obs('2160-0', 0.5, 'mg/dL', '20260901', { value: '<value xsi:type="PQ" value="&lt;0.5" unit="mg/dL"/>' }),
    obs('98979-8', 90, 'mL/min/{1.73_m2}', '20260902', { value: '<value xsi:type="PQ" value="&gt;90" unit="mL/min/{1.73_m2}"/>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260903', { value: '<value xsi:type="PQ" value="≥6" unit="mmol/L"/>' }),
    obs('2160-0', 1, 'mg/dL', '20260904', { value: '<value xsi:type="IVL_PQ"><high value="0.6" unit="mg/dL" inclusive="false"/></value>' }), // "below 0.6"
    obs('2823-3', 4.5, 'mmol/L', '20260905', { value: '<value xsi:type="ST">Hemolyzed</value>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260905', { value: '<value xsi:type="CD" code="260385009" codeSystem="2.16.840.1.113883.6.96" displayName="Negative"/>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260906', { value: '<value value="4.5" unit="mmol/L"/>' }), // no xsi:type: not trusted to be a quantity
    obs('2823-3', 4.5, 'mmol/L', '20260906', { value: '<value xsi:type="PQ" unit="mmol/L"/>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260907', { value: '<value xsi:type="PQ" value="abc" unit="mmol/L"/>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260907', { value: '<value xsi:type="PQ" value="1e3" unit="mmol/L"/>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260907', { value: '<value xsi:type="PQ" value="Infinity" unit="mmol/L"/>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260908', { value: '<value xsi:type="PQ" value="4.1" unit="mmol/L"/><value xsi:type="PQ" value="4.2" unit="mmol/L"/>' }), // two values
    obs('2823-3', 4.5, 'mmol/L', '20260908', { value: '' }),
    obs('2823-3', 4.4, 'mmol/L', '20260909', { value: '<value xsi:type="hl7:PQ" xmlns:hl7="urn:hl7-org:v3" value="4.4" unit="mmol/L"/>' }), // a prefixed type name is still PQ
    obs('2823-3', 4.3, 'mmol/L', '20260910'),
  ))], opts(), {
    counts: { files: 1, read: 1, observations: 15, noValue: 9, notExact: 4, found: 2 },
    rows: ['2026-09-10 potassium 4.3 mmol/L', '2026-09-09 potassium 4.4 mmol/L'],
    problemsInclude: ['“<0.5” is not a single number', '“>90” is not a single number', '“≥6” is not a single number', 'a range or a limit', 'the result is not a single number'],
  }],
  ['a value the lab left blank (nullFlavor) is skipped and counted, and so is a code, a day or an observation that is blank', [file('HealthSummary.xml', labs(
    obs('2823-3', 4.5, 'mmol/L', '20260901', { value: '<value xsi:type="PQ" nullFlavor="NI"/>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260902', { value: '<value nullFlavor="UNK"/>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260903', { code: '<code nullFlavor="NI"/>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260904', { time: '<effectiveTime nullFlavor="UNK"/>' }),
    obs('2823-3', 4.5, 'mmol/L', '20260905', { time: '<effectiveTime nullFlavor="UNK"><low nullFlavor="UNK"/></effectiveTime>' }),
    '<observation classCode="OBS" moodCode="EVN" nullFlavor="NI">' + template(RESULT_OBSERVATION) + '</observation>',
    obs('2823-3', 4.4, 'mmol/L', '20260906'),
  ))], opts(), {
    counts: { files: 1, read: 1, observations: 7, noValue: 2, unknownCode: 2, badDate: 2, found: 1 },
    rows: ['2026-09-06 potassium 4.4 mmol/L'],
    problemsInclude: ['the lab left the value blank (nullFlavor “NI”)', 'the lab left the value blank (nullFlavor “UNK”)', 'no date'],
  }],
  ['the plausible-range check is the one the CSV import uses', [file('HealthSummary.xml', labs(
    obs('2823-3', 15, 'mmol/L', '20260901'), obs('2160-0', 150, 'mg/dL', '20260901'), obs('2823-3', -4, 'mmol/L', '20260901'),
    obs('2823-3', 0, 'mmol/L', '20260902'), obs('4548-4', 1.2, '%', '20260902'), obs('2823-3', 6.1, 'mmol/L', '20260903'),
  ))], opts(), {
    counts: { files: 1, read: 1, observations: 6, refused: 5, found: 1 },
    rows: ['2026-09-03 potassium 6.1 mmol/L'],
    problemsInclude: ['Potassium 15.0 mmol/L is outside the plausible range 1.5–9 mmol/L', 'Creatinine (blood) 150.00 mg/dL is outside the plausible range 0.1–25 mg/dL', 'Potassium must be a non-negative number'],
  }],
  // ---- the day ---------------------------------------------------------------------------------------------------------------
  ['the day: effectiveTime/@value, else effectiveTime/low/@value; a date alone is used as written', [file('HealthSummary.xml', labs(
    obs('2823-3', 4.1, 'mmol/L', '20260901'),
    obs('2823-3', 4.2, 'mmol/L', '', { time: '<effectiveTime><low value="20260902"/><high value="20260903"/></effectiveTime>' }),
    obs('2823-3', 4.3, 'mmol/L', '', { time: '<effectiveTime value="20260904"><low value="20260801"/></effectiveTime>' }),
    obs('2823-3', 4.4, 'mmol/L', '', { time: '<effectiveTime value=""><low value="20260905"/></effectiveTime>' }),
    obs('2823-3', 4.5, 'mmol/L', '', { time: '<effectiveTime><high value="20260906"/></effectiveTime>' }),
    obs('2823-3', 4.6, 'mmol/L', '', { time: '' }),
  ))], opts(), {
    counts: { files: 1, read: 1, observations: 6, badDate: 2, found: 4 },
    rows: ['2026-09-05 potassium 4.4 mmol/L', '2026-09-04 potassium 4.3 mmol/L', '2026-09-02 potassium 4.2 mmol/L', '2026-09-01 potassium 4.1 mmol/L'],
    problemsInclude: ['no date'],
  }],
  ['a time with a time zone is the calendar day on this device; a day alone or a time without a zone is used as written', [file('HealthSummary.xml', labs(
    obs('2823-3', 4.1, 'mmol/L', '20260902033000+0000'),
    obs('2823-3', 4.2, 'mmol/L', '20260903223000-0700'),
    obs('2823-3', 4.3, 'mmol/L', '20260904'),
    obs('2823-3', 4.4, 'mmol/L', '20260905235900'),
    obs('2823-3', 4.5, 'mmol/L', '20260906001000.123+0200'),
    obs('2823-3', 4.6, 'mmol/L', '202609070830-0700'),
    obs('2823-3', 4.7, 'mmol/L', '20260908-0700'), // a zone on a date alone changes nothing
  ))], opts({ tzOffsetMinutes: -420 }), { // a device seven hours behind UTC (summer time on the US west coast)
    counts: { files: 1, read: 1, observations: 7, found: 7 },
    rows: [
      '2026-09-08 potassium 4.7 mmol/L', '2026-09-07 potassium 4.6 mmol/L', '2026-09-05 potassium 4.4 mmol/L', '2026-09-05 potassium 4.5 mmol/L',
      '2026-09-04 potassium 4.3 mmol/L', '2026-09-03 potassium 4.2 mmol/L', '2026-09-01 potassium 4.1 mmol/L',
    ],
  }],
  ['a device ahead of UTC sees the next day', [file('HealthSummary.xml', labs(obs('2823-3', 4.1, 'mmol/L', '20260902203000+0000')))], opts({ tzOffsetMinutes: 600 }), {
    counts: { files: 1, read: 1, observations: 1, found: 1 }, rows: ['2026-09-03 potassium 4.1 mmol/L'],
  }],
  ['future days, days before 1900 and days that are not days are refused', [file('HealthSummary.xml', labs(
    obs('2823-3', 4.1, 'mmol/L', '20261015'), obs('2823-3', 4.2, 'mmol/L', '20261016'), obs('2823-3', 4.3, 'mmol/L', '20261017'),
    obs('2823-3', 4.4, 'mmol/L', '20990101000000+0000'), obs('2823-3', 4.5, 'mmol/L', '18991231'), obs('2823-3', 4.6, 'mmol/L', '202609'),
    obs('2823-3', 4.7, 'mmol/L', '2026'), obs('2823-3', 4.8, 'mmol/L', '20260230'), obs('2823-3', 4.9, 'mmol/L', 'last Tuesday'),
    obs('2823-3', 5.0, 'mmol/L', '20260901250000+0000'), obs('2823-3', 5.1, 'mmol/L', '2026-09-01'), obs('2823-3', 5.2, 'mmol/L', '2026090108'),
  ))], opts(), {
    counts: { files: 1, read: 1, observations: 12, badDate: 10, found: 2 },
    rows: ['2026-10-16 potassium 4.2 mmol/L', '2026-10-15 potassium 4.1 mmol/L'], // tomorrow: one day of slack, as the server
    problemsInclude: ['in the future', 'is before 1900', 'has no day', 'is not a real date', 'is not a date the app can read', 'is not a real time'],
  }],
  ['without a today the future is not checked (the page always gives one)', [file('HealthSummary.xml', labs(obs('2823-3', 4.4, 'mmol/L', '20990101')))], { tzOffsetMinutes: 0 }, {
    counts: { files: 1, read: 1, observations: 1, found: 1 }, rows: ['2099-01-01 potassium 4.4 mmol/L'],
  }],
  // ---- repeats and what is already saved -------------------------------------------------------------------------------------
  ['the same result twice in a file, in two files, or under two codes, is one row', [
    file('one.xml', labs(obs('2160-0', 1.7, 'mg/dL', '20260901'), obs('2160-0', 1.7, 'mg/dL', '20260901'), obs('14682-9', 150.3, 'umol/L', '20260901'))),
    file('two.xml', labs(obs('2160-0', 1.7, 'mg/dL', '20260901'), obs('2160-0', 1.7, 'mg/dL', '20260902'))),
  ], opts(), { counts: { files: 2, read: 2, observations: 5, duplicates: 3, found: 2 }, rows: ['2026-09-02 creatinine 1.70 mg/dL', '2026-09-01 creatinine 1.70 mg/dL'] }],
  ['a result the person already has is marked saved', [file('HealthSummary.xml', labs(obs('2823-3', 4.6, 'mmol/L', '20260901'), obs('2160-0', 1.7, 'mg/dL', '20260901')))],
    opts({ existing: [{ analyte: 'potassium', taken_on: '2026-09-01', value: 4.6 }, { analyte: 'creatinine', taken_on: '2026-09-02', value: 1.7 }, { analyte: 'nonsense', taken_on: '2026-09-01', value: 1 }] }), {
      counts: { files: 1, read: 1, observations: 2, found: 2, saved: 1 },
      rows: ['2026-09-01 potassium 4.6 mmol/L', '2026-09-01 creatinine 1.70 mg/dL'], savedRows: [true, false],
    }],
  // ---- files the app refuses before it reads them ----------------------------------------------------------------------------
  ['a file with a DOCTYPE or an ENTITY declaration is refused before it is parsed, whatever it declares', [
    file('doctype.xml', `<?xml version="1.0"?>\n<!DOCTYPE ClinicalDocument SYSTEM "CDA.dtd">${labs(obs('2823-3', 4.4, 'mmol/L', '20260901')).replace(/^<\?xml[^>]*\?>\s*(<\?xml-stylesheet[^>]*\?>\s*)?/, '')}`),
    file('billion-laughs.xml', '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]><lolz>&lol2;</lolz>'),
    file('external.xml', '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><ClinicalDocument xmlns="urn:hl7-org:v3">&xxe;</ClinicalDocument>'),
    file('lowercase.xml', '<!doctype html><html></html>'),
    file('spaced.xml', '<! DOCTYPE x><x/>'),
    file('entity-only.xml', `<ClinicalDocument ${NS}><!ENTITY x "y"></ClinicalDocument>`),
    file('in-a-comment.xml', labs(obs('2823-3', 4.4, 'mmol/L', '20260901')).replace('<ClinicalDocument', '<!-- <!DOCTYPE x> --><ClinicalDocument')), // refused too: nothing is cleaned
    file('escaped.xml', labs(obs('2823-3', 4.5, 'mmol/L', '20260902')).replace('Health Summary', 'A &lt;!DOCTYPE note')), // text that only talks about one is fine
  ], opts(), { counts: { files: 8, read: 1, doctype: 7, observations: 1, found: 1 }, rows: ['2026-09-02 potassium 4.5 mmol/L'] }],
  ['files that are not XML, empty, cut short or malformed, and one with a byte order mark first', [
    file('notes.xml', 'Potassium 4.5 on Sept 1'),
    file('empty.xml', ''),
    file('cut.xml', labs(obs('2823-3', 4.4, 'mmol/L', '20260901')).slice(0, 900)),
    file('mismatch.xml', labs(obs('2823-3', 4.4, 'mmol/L', '20260901')).replace('</title>', '</titel>')),
    file('html-entity.xml', labs(obs('2823-3', 4.4, 'mmol/L', '20260901')).replace('Health Summary', 'Health&nbsp;Summary')), // an HTML entity is not XML
    file('two-roots.xml', `${labs(obs('2823-3', 4.4, 'mmol/L', '20260901'))}<extra/>`),
    file('unquoted.xml', '<ClinicalDocument xmlns=urn:hl7-org:v3/>'),
    file('html.xml', '<html><body><script>alert(1)</script><br></body></html>'),
    file('json.xml', '{"resourceType": "Observation"}'),
    file('bom.xml', `﻿${labs(obs('2823-3', 4.4, 'mmol/L', '20260901'))}`),
  ], opts(), { counts: { files: 10, read: 1, notXml: 9, observations: 1, found: 1 }, rows: ['2026-09-01 potassium 4.4 mmol/L'] }],
  ['XML that is not a C-CDA health summary is counted as that', [
    file('xhtml.xml', '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Potassium 4.4 mmol/L</p></body></html>'),
    file('fhir.xml', '<Observation xmlns="http://hl7.org/fhir"><status value="final"/><code><coding><system value="http://loinc.org"/><code value="2823-3"/></coding></code></Observation>'),
    file('no-namespace.xml', labs(obs('2823-3', 4.4, 'mmol/L', '20260901')).replace(' xmlns="urn:hl7-org:v3"', '')),
    file('wrong-root.xml', '<Summary xmlns="urn:hl7-org:v3"/>'),
    file('lowercase-root.xml', '<clinicalDocument xmlns="urn:hl7-org:v3"/>'),
    file('empty-doc.xml', `<ClinicalDocument ${NS}/>`),
  ], opts(), { counts: { files: 6, read: 1, notCcda: 5, noResults: 1 }, rows: [] }],
  ['a file the page could not read, and a file over 5 MB that is never read', [
    { name: 'unreadable.xml', unreadable: true },
    { name: 'huge.xml', size: 6000000 },
    { name: 'just-over.xml', size: 5242881, text: labs(obs('2823-3', 4.4, 'mmol/L', '20260901')) },
    { name: 'exactly-5mb.xml', size: 5242880, text: labs(obs('2823-3', 4.5, 'mmol/L', '20260902')) },
    { name: 'no-text.xml', size: 10 },
  ], opts(), { counts: { files: 5, read: 1, tooBig: 2, unreadable: 2, observations: 1, found: 1 }, rows: ['2026-09-02 potassium 4.5 mmol/L'] }],
  ['a file whose text is over 5 MB is skipped even when the page gave no size', [
    { name: 'long.xml', repeat: { prefix: '<a>', item: '<b/>', separator: '', count: 1400000, suffix: '</a>' } },
  ], opts(), { counts: { files: 1, tooBig: 1 }, rows: [] }],
  ['a file nested too deeply or with too many elements is skipped, not walked, and nothing from it is kept', [
    { name: 'deep.xml', text: `<ClinicalDocument ${NS}>${'<component><section>'.repeat(40)}${'</section></component>'.repeat(40)}</ClinicalDocument>` },
    { name: 'deep-ok.xml', text: `<ClinicalDocument ${NS}><component><structuredBody>${'<component><section>'.repeat(20)}${results(organizer(obs('2823-3', 4.4, 'mmol/L', '20260901')))}${'</section></component>'.repeat(20)}</structuredBody></component></ClinicalDocument>` },
    { name: 'wide.xml', repeat: { prefix: `<ClinicalDocument ${NS}><component><structuredBody>${results('')}`.replace('</section></component>', ''), item: '<entry/>', separator: '', count: 200001, suffix: '</section></component></structuredBody></component></ClinicalDocument>' } },
    { name: 'deep-in-results.xml', text: ccda(results(organizer(obs('2823-3', 4.5, 'mmol/L', '20260902')), entry(`${'<organizer><component>'.repeat(40)}${'</component></organizer>'.repeat(40)}`))) },
  ], opts(), { counts: { files: 4, read: 1, tooComplex: 3, observations: 1, found: 1 }, rows: ['2026-09-01 potassium 4.4 mmol/L'] }],
  // ---- text and people in a file -----------------------------------------------------------------------------------------------
  ['hostile text in a file is only ever quoted, shortened, and never an element', [file('HealthSummary.xml', labs(
    obs('2823-3', 4.4, '&lt;img src=x onerror=alert(1)&gt;', '20260901'),
    obs('2160-0', 4.4, 'mg/dL', '&lt;script&gt;alert(1)&lt;/script&gt;'),
    obs('2823-3', 4.4, 'mmol/L', '20260901', { value: '<value xsi:type="PQ" value="‮&lt;4.4" unit="mmol/L"/>' }),
    obs('2823-3', 4.4, 'mmol/L', '20260901', { value: '<value xsi:type="PQ" value="4.4" unit="&lt;b&gt;mg/dL&lt;/b&gt;"/>' }),
  ))], opts(), { counts: { files: 1, read: 1, observations: 4, badUnit: 2, badDate: 1, noValue: 1 }, rows: [] }],
  ['the people in a file are never read: a name, an id, an address, a provider and a note appear in no answer', [file('HealthSummary.xml', labs(
    obs('2823-3', 4.4, 'mmol/L', '20260901', { after: '<entryRelationship typeCode="SUBJ"><act classCode="ACT" moodCode="EVN"><code code="48767-8" codeSystem="2.16.840.1.113883.6.1"/><text>Sam Example called back, Dr Example agrees</text></act></entryRelationship>' }),
  ))], opts(), { counts: { files: 1, read: 1, observations: 1, found: 1 }, rows: ['2026-09-01 potassium 4.4 mmol/L'] }],
  ['a pick of many kinds of file, as a portal and a phone have them', [
    file('visit-1.xml', labs(obs('2823-3', 4.6, 'mmol/L', '20260901'), obs('2160-0', 1.7, 'mg/dL', '20260901'))),
    file('visit-2.xml', labs(obs('2823-3', 5.9, 'mmol/L', '20260920', { status: '<statusCode code="active"/>' }), obs('2823-3', 18, 'mg/dL', '20260920'))),
    file('notes.txt', 'not xml'),
    file('summary.xml', ccda(component(section(template('2.16.840.1.113883.10.20.22.2.6.1'), '', 'Allergies')))),
    file('fhir.xml', '<Observation xmlns="http://hl7.org/fhir"/>'),
    file('old.xml', `<!DOCTYPE x>${labs(obs('2823-3', 4.6, 'mmol/L', '20260901'))}`),
  ], opts(), { counts: { files: 6, read: 3, notXml: 1, notCcda: 1, doctype: 1, noResults: 1, observations: 4, wrongStatus: 1, badUnit: 1, found: 2 }, rowCount: 2 }],
  ['no files', [], opts(), { problem: 'No files were chosen.', counts: {}, rows: [] }],
];

// ---- picks with limits that need their own list of files -----------------------------------------------------------------------
const tinyDoc = labs(obs('2823-3', 4.4, 'mmol/L', '20260901'));
CASES.push(['more than 20 files are refused as a pick, before any is read', { repeat_file: { name: 'visit-{n}.xml', text: tinyDoc, count: C.MAX_FILES + 1 } }, opts(), {
  problem: 'You chose 21 files; the app reads up to 20 at a time. Choose fewer files, for example only your latest health summary.', counts: { files: 21 }, rows: [],
}]);
CASES.push(['exactly 20 files are read', { repeat_file: { name: 'visit-{n}.xml', text: labs(obs('2823-3', 4.4, 'mmol/L', '{date}')), count: C.MAX_FILES, dates_from: '20260101' } }, opts(), {
  counts: { files: 20, read: 20, observations: 20, found: 20 }, rowCount: 20,
}]);
// 1,005 distinct results in one file: the newest 1,000 are shown, 5 are counted as left out (POST /api/labs/import takes 1 to 1,000).
CASES.push(['a file with over a thousand results shows the newest thousand', [{
  name: 'big.xml',
  repeat: {
    prefix: `<ClinicalDocument ${NS}><component><structuredBody><component><section>${REQUIRED}<entry><organizer classCode="BATTERY" moodCode="EVN">${template(RESULT_ORGANIZER)}`,
    item: `<component>${obs('2823-3', 4.4, 'mmol/L', '{date}', { after: '' }).replace(/<performer.*<\/performer>/, '').replace(/<id [^>]*\/>/, '')}</component>`,
    separator: '',
    count: 1005,
    suffix: '</organizer></entry></section></component></structuredBody></component></ClinicalDocument>',
    dates_from: '20230101',
  },
}], opts(), {
  counts: { files: 1, read: 1, observations: 1005, found: 1000, leftOut: 5 }, rowCount: 1000, firstRows: ['2025-10-01 potassium 4.4 mmol/L'],
}]);

// ---- build the file and check each `want` ----------------------------------------------------------------------------------------
// A file with a recipe instead of its text: {name, repeat: {prefix, item, separator, count, suffix, dates_from}}; "{date}" in the item is
// the nth day (YYYYMMDD) from dates_from, so that the repeats are distinct results. Many files: {repeat_file: {name, text, count,
// dates_from}} (a pick given as that object instead of a list; "{n}" in the name is the number of the file, "{date}" in the text its day).
const expandFile = (f) => {
  if (!f.repeat) return f;
  const { prefix, item, separator, count, suffix, dates_from: from } = f.repeat;
  return { name: f.name, text: prefix + Array.from({ length: count }, (_, i) => (from ? item.replace('{date}', addDays(from, i)) : item)).join(separator) + suffix };
};
const expandFiles = (list) => (Array.isArray(list) ? list.map(expandFile)
  : Array.from({ length: list.repeat_file.count }, (_, i) => ({
    name: list.repeat_file.name.replace('{n}', String(i)),
    text: list.repeat_file.dates_from ? list.repeat_file.text.replace('{date}', addDays(list.repeat_file.dates_from, i)) : list.repeat_file.text,
  })));
const rowText = (r) => `${r.taken_on} ${r.analyte} ${r.display}`;
const problems = [];
const cases = CASES.map(([name, files, options, want]) => {
  const expected = plain(C.analyse(expandFiles(files), { ...options, parseXml: parse }));
  // The hand-written expectation: every count that is not zero is listed, every other count is zero.
  const zero = plain(C.start({ parseXml: parse }).counts);
  const wantCounts = { ...zero, ...want.counts };
  if (!isDeepStrictEqual(expected.counts, wantCounts)) problems.push(`${name}: counts\n   got  ${JSON.stringify(expected.counts)}\n   want ${JSON.stringify(wantCounts)}`);
  const rows = expected.results.map(rowText);
  if (want.rows && !isDeepStrictEqual(rows, want.rows)) problems.push(`${name}: rows\n   got  ${JSON.stringify(rows)}\n   want ${JSON.stringify(want.rows)}`);
  if (want.rowCount !== undefined && rows.length !== want.rowCount) problems.push(`${name}: ${rows.length} rows, want ${want.rowCount}`);
  if (want.firstRows && !isDeepStrictEqual(rows.slice(0, want.firstRows.length), want.firstRows)) problems.push(`${name}: first rows\n   got  ${JSON.stringify(rows.slice(0, want.firstRows.length))}\n   want ${JSON.stringify(want.firstRows)}`);
  if (want.savedRows && !isDeepStrictEqual(expected.results.map((r) => r.saved), want.savedRows)) problems.push(`${name}: saved flags ${JSON.stringify(expected.results.map((r) => r.saved))}`);
  for (const part of want.problemsInclude || []) {
    if (!expected.problems.some((p) => p.problem.includes(part))) problems.push(`${name}: no refusal says ${JSON.stringify(part)}: ${JSON.stringify(expected.problems.map((p) => p.problem))}`);
  }
  if ((want.problem || null) !== expected.problem) problems.push(`${name}: problem ${JSON.stringify(expected.problem)}, want ${JSON.stringify(want.problem || null)}`);
  const answer = JSON.stringify(expected);
  for (const secret of ['Sam', 'Example', 'example-0001', 'example-0002', 'Exampleville', 'Street', 'tel:', '1970', 'called back']) {
    if (answer.includes(secret)) problems.push(`${name}: "${secret}" from a file is in the answer`);
  }
  const stored = Array.isArray(files) ? files.map((f) => (f.repeat ? { name: f.name, repeat: f.repeat } : f)) : files;
  return { name, files: stored, options, expected };
});
if (problems.length) {
  console.error(problems.join('\n'));
  process.exit(1);
}

const doc = {
  about: 'js/engine/ccda_labs.js answers (Lab results → Import from a patient portal file, a C-CDA XML health summary parsed and read on the device); generated by tests/js/gen_ccda_labs_vectors.mjs from hand-written documents and hand-written expectations (the script stops if the module disagrees), replayed by tests/js/run_vectors.mjs with the dev-only parser tests/js/mini_xml.mjs, cross-checked against app/units.py by tests/test_ccda_labs.py',
  limits: { max_files: C.MAX_FILES, max_file_bytes: C.MAX_FILE_BYTES, max_elements: C.MAX_ELEMENTS, max_depth: C.MAX_DEPTH, max_records: FL.MAX_RECORDS, max_collect: FL.MAX_COLLECT, max_results: FL.MAX_RESULTS, max_problems: FL.MAX_PROBLEMS },
  oids: { loinc: C.LOINC_OID, results_section: C.RESULTS_SECTION_OIDS, result_organizer: C.RESULT_ORGANIZER_OID, result_observation: C.RESULT_OBSERVATION_OID, results_section_code: C.RESULTS_SECTION_CODE, namespace: C.NS_HL7 },
  cases,
};
writeFileSync(OUT, `${JSON.stringify(doc, null, 1)}\n`);
console.log(`wrote ${OUT}: ${cases.length} cases`);
