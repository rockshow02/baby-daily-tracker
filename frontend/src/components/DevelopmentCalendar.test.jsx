import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import {beforeEach,describe,expect,it,vi} from "vitest";
import DevelopmentCalendar from "./DevelopmentCalendar";
import {api} from "../api/client";

vi.mock("../api/client",()=>({api:{developmentCalendar:vi.fn()}}));
const child={id:7,name:"Nara"};
const response={items:[
  {id:"goal-1",type:"goal",date:"2026-08-06",title:"Latihan tengkurap",summary:"Target keluarga",icon:"🎯"},
  {id:"medication-2026-08-06",type:"medication",date:"2026-08-06",title:"Jadwal obat",summary:"2 waktu pemberian terjadwal",icon:"💊"},
],privacy_note:"Kalender tidak menampilkan data medis sensitif."};

describe("DevelopmentCalendar",()=>{
  beforeEach(()=>{vi.clearAllMocks();vi.setSystemTime(new Date("2026-08-06T03:00:00Z"));api.developmentCalendar.mockResolvedValue(response);});
  it("shows a month grid and selected-day agenda",async()=>{render(<DevelopmentCalendar child={child} onClose={vi.fn()}/>);expect(await screen.findByText("Agustus 2026")).toBeInTheDocument();fireEvent.click(screen.getByRole("button",{name:"Pilih tanggal 2026-08-06"}));expect(screen.getByText("Latihan tengkurap")).toBeInTheDocument();expect(screen.getByText("2 waktu pemberian terjadwal")).toBeInTheDocument();});
  it("navigates months through a server request",async()=>{render(<DevelopmentCalendar child={child} onClose={vi.fn()}/>);await screen.findByText("Agustus 2026");fireEvent.click(screen.getByRole("button",{name:"Bulan berikutnya"}));await waitFor(()=>expect(api.developmentCalendar).toHaveBeenLastCalledWith(7,expect.objectContaining({month:"2026-09"})));});
  it("sends category filters and closes",async()=>{const close=vi.fn();render(<DevelopmentCalendar child={child} onClose={close}/>);await screen.findByText("Agustus 2026");fireEvent.click(screen.getByRole("button",{name:"Obat"}));await waitFor(()=>expect(api.developmentCalendar).toHaveBeenLastCalledWith(7,expect.objectContaining({categories:expect.not.arrayContaining(["medication"])})));fireEvent.click(screen.getByRole("button",{name:"Tutup"}));expect(close).toHaveBeenCalled();});
});
