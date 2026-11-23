import { getCollection } from 'astro:content';

export const home = import.meta.env.BASE_URL;
export const guideHref = (id: string) => `${home}guides/${id}/`;

const groups = [
  { label: 'Getting started', items: [['', 'Quickstart']] },
  { label: 'Guides', items: [['policies', 'Shared Python policies'], ['photos', 'Photo sharing']] },
  { label: 'Design decisions', items: [['choosing-policy', 'Python or Cedar?']] },
  { label: 'Integrations', items: [['sqlalchemy', 'SQLAlchemy (source only)'], ['fastapi', 'FastAPI'], ['flask', 'Flask'], ['django', 'Django']] },
  { label: 'Cedarpy guides', items: [['cedarpy', 'Python bindings'], ['cedarpy-pst', 'Policy syntax trees'], ['cedarpy-partial', 'Partial authorization'], ['cedarpy-asyncio', 'Threads and asyncio']] },
] as const;

export async function getNavigation() {
  const ids = new Set((await getCollection('guides')).map(entry => entry.id));
  return groups.map(({ label, items }) => ({
    label,
    items: items.filter(([id]) => !id || ids.has(id)).map(([id, label]) => ({
      id, label, href: id ? guideHref(id) : home,
    })),
  })).filter(group => group.items.length);
}
