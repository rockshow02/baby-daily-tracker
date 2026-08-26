import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MemoryStorageManager from "./MemoryStorageManager";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: {
  memoryStorage: vi.fn(), cleanupMemoryStorage: vi.fn(), optimizeMemoryPhoto: vi.fn(),
} }));
const child={id:1,name:"Nara"};
const overview={photo_count:2,actual_bytes:2048,warning_bytes:1048576,usage_percent:0.2,warning:false,
  missing_file_count:0,orphan_file_count:1,orphan_bytes:512,largest:[{id:8,caption:"Senyum",occurred_date:"2026-08-20",size_bytes:1500}]};

describe("MemoryStorageManager",()=>{
  beforeEach(()=>{vi.clearAllMocks();api.memoryStorage.mockResolvedValue(overview);});
  it("shows storage health without exposing filenames",async()=>{render(<MemoryStorageManager child={child} onClose={vi.fn()}/>);expect(await screen.findByText("2.0 KB")).toBeInTheDocument();expect(screen.getByText("1")).toBeInTheDocument();expect(document.body.textContent).not.toContain("memory_1_");});
  it("requires dry-run and exact confirmation before cleanup",async()=>{api.cleanupMemoryStorage.mockResolvedValueOnce({would_delete_count:1,would_delete_bytes:512,deleted_count:0}).mockResolvedValueOnce({deleted_count:1});render(<MemoryStorageManager child={child} onClose={vi.fn()}/>);fireEvent.click(await screen.findByRole("button",{name:"Dry-run pembersihan"}));expect(await screen.findByText(/Akan menghapus 1 file/)).toBeInTheDocument();const apply=screen.getByRole("button",{name:"Terapkan pembersihan"});expect(apply).toBeDisabled();fireEvent.change(screen.getByPlaceholderText("Ketik BERSIHKAN"),{target:{value:"BERSIHKAN"}});fireEvent.click(apply);await waitFor(()=>expect(api.cleanupMemoryStorage).toHaveBeenLastCalledWith(1,{apply:true,confirmation:"BERSIHKAN"}));});
  it("optimizes one selected entry",async()=>{api.optimizeMemoryPhoto.mockResolvedValue({changed:true});render(<MemoryStorageManager child={child} onClose={vi.fn()} onChanged={vi.fn()}/>);fireEvent.click(await screen.findByRole("button",{name:"Optimalkan"}));await waitFor(()=>expect(api.optimizeMemoryPhoto).toHaveBeenCalledWith(1,8));});
});
