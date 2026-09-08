import { createContext, useContext, useState, type ReactNode } from "react";

const Context = createContext<{ open: boolean; question: string; ask: (question: string) => void; setOpen: (open: boolean) => void }>({ open: false, question: "", ask: () => {}, setOpen: () => {} });
export function AssistantProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  return <Context.Provider value={{ open, question, setOpen, ask: question => { setQuestion(question); setOpen(true); } }}>{children}</Context.Provider>;
}
export const useAssistant = () => useContext(Context);
