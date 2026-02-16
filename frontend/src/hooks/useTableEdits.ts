import { useProjectStore } from '../store/projectStore';

export function useTableEdits() {
  const { corrections, editCount } = useProjectStore();
  return { corrections, editCount };
}
