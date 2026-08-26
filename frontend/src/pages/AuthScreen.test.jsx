import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuthScreen from "./AuthScreen";

const auth = vi.hoisted(() => ({ login: vi.fn(), register: vi.fn() }));

vi.mock("../context/AuthContext", () => ({ useAuth: () => auth }));

describe("AuthScreen", () => {
  beforeEach(() => {
    auth.login.mockReset();
    auth.register.mockReset();
  });

  it("submits login credentials through the existing auth contract", async () => {
    auth.login.mockResolvedValue({});
    render(<AuthScreen />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ibu@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "rahasia" } });
    fireEvent.click(screen.getByRole("button", { name: "Masuk ke aplikasi" }));

    await waitFor(() => expect(auth.login).toHaveBeenCalledWith("ibu@example.com", "rahasia"));
  });

  it("switches to registration without losing accessible labels", () => {
    render(<AuthScreen />);
    fireEvent.click(screen.getByRole("button", { name: "Daftar" }));

    expect(screen.getByLabelText("Nama Anda")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Buat akun" })).toBeInTheDocument();
  });

  it("never renders [object Object] for a structured failure", async () => {
    auth.login.mockRejectedValue({ message: { detail: "internal" } });
    render(<AuthScreen />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ibu@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "rahasia" } });
    fireEvent.click(screen.getByRole("button", { name: "Masuk ke aplikasi" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Belum berhasil memproses akun. Coba lagi.");
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
  });
});
