import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { MessageSquare, Ticket, BookOpen, BarChart2 } from "lucide-react";
import ChatTab from "@/components/ChatTab";
import TicketsTab from "@/components/TicketsTab";
import KnowledgeTab from "@/components/KnowledgeTab";
import ReportsTab from "@/components/ReportsTab";

export default function App() {
  return (
    <div className="flex h-screen flex-col bg-background">
      {/* Header */}
      <header className="flex h-14 items-center border-b px-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground text-xs font-bold">
            A
          </div>
          <span className="font-semibold tracking-tight">Agora</span>
          <span className="text-xs text-muted-foreground">IT Service Desk</span>
        </div>
      </header>

      {/* Main content */}
      <Tabs defaultValue="chat" className="flex flex-1 flex-col overflow-hidden">
        <div className="border-b px-6 pt-2">
          <TabsList className="h-10 gap-1 bg-transparent p-0">
            <TabsTrigger
              value="chat"
              className="flex items-center gap-1.5 rounded-none border-b-2 border-transparent px-3 pb-2 pt-1.5 text-sm data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              <MessageSquare className="h-4 w-4" />
              Chat
            </TabsTrigger>
            <TabsTrigger
              value="tickets"
              className="flex items-center gap-1.5 rounded-none border-b-2 border-transparent px-3 pb-2 pt-1.5 text-sm data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              <Ticket className="h-4 w-4" />
              Tickets
            </TabsTrigger>
            <TabsTrigger
              value="knowledge"
              className="flex items-center gap-1.5 rounded-none border-b-2 border-transparent px-3 pb-2 pt-1.5 text-sm data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              <BookOpen className="h-4 w-4" />
              Knowledge
            </TabsTrigger>
            <TabsTrigger
              value="reports"
              className="flex items-center gap-1.5 rounded-none border-b-2 border-transparent px-3 pb-2 pt-1.5 text-sm data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              <BarChart2 className="h-4 w-4" />
              Reports
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="chat" className="mt-0 flex-1 overflow-hidden">
          <ChatTab />
        </TabsContent>
        <TabsContent value="tickets" className="mt-0 flex-1 overflow-auto">
          <TicketsTab />
        </TabsContent>
        <TabsContent value="knowledge" className="mt-0 flex-1 overflow-auto">
          <KnowledgeTab />
        </TabsContent>
        <TabsContent value="reports" className="mt-0 flex-1 overflow-auto">
          <ReportsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
