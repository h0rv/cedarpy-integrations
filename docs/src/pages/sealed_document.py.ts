import script from '../../../examples/sealed_document.py?raw';

export function GET() {
  return new Response(script, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
