"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { fetchSuggestions } from "@/lib/client/search-api";
import type { SuggestItem } from "@/lib/types";

/**
 * 検索入力＋サジェスト（DS-API-004・004a、設計仕様書 P2 追補a 6.1・3.2）。
 * ヘッダーの検索欄（デスクトップの常設入力・モバイルの検索パネル）の両方で使う「頭脳」部分。
 *
 * - combobox パターン（WAI-ARIA）: input に `role="combobox"`・`aria-expanded`・`aria-controls`・
 *   `aria-activedescendant`。候補一覧は `role="listbox"`／各候補は `role="option"`。
 * - キーボード: ↓/↑ で候補を移動、Enter で選択中の候補（無ければ入力値）を検索実行、
 *   Escape で候補を閉じる（既に閉じていれば `onEscape` で呼び出し側に委ねる＝モバイルパネルを閉じる）。
 * - 入力から 300ms デバウンスして `GET /api/search/suggest` を呼ぶ（BFF 経由。DS-PRC-004a）。
 * - Enter・候補選択のどちらも `/search?q=...` への遷移になる（商品詳細には飛ばない。6.1 のとおり）。
 */

export interface SearchBoxProps {
  /** マウント時に入力へフォーカスする（モバイルパネルを開いた直後などに使う） */
  autoFocus?: boolean;
  /** 検索を実行して遷移した後に呼ばれる（モバイルパネルを閉じる用途） */
  onNavigate?: () => void;
  /** 候補が閉じている状態で Escape を押したときに呼ばれる（モバイルパネルを閉じる用途） */
  onEscape?: () => void;
  placeholder?: string;
  className?: string;
  inputClassName?: string;
}

const DEBOUNCE_MS = 300;

export default function SearchBox({
  autoFocus = false,
  onNavigate,
  onEscape,
  placeholder = "商品を探す",
  className = "",
  inputClassName = "",
}: SearchBoxProps) {
  const router = useRouter();
  const listboxId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [value, setValue] = useState("");
  const [items, setItems] = useState<SuggestItem[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      abortRef.current?.abort();
    },
    [],
  );

  const closeList = useCallback(() => {
    setOpen(false);
    setActiveIndex(-1);
    setItems([]);
  }, []);

  const scheduleSuggest = useCallback((term: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    abortRef.current?.abort();
    if (term.trim().length === 0) {
      setItems([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(() => {
      const controller = new AbortController();
      abortRef.current = controller;
      fetchSuggestions(term, controller.signal)
        .then((res) => {
          setItems(res.items);
          setOpen(res.items.length > 0);
          setActiveIndex(-1);
        })
        .catch(() => {
          // サジェストは補助機能。失敗しても検索そのものは Enter で続行できるため無視する
        });
    }, DEBOUNCE_MS);
  }, []);

  const goToSearch = useCallback(
    (term: string) => {
      const trimmed = term.trim();
      if (trimmed.length === 0) return;
      closeList();
      router.push(`/search?q=${encodeURIComponent(trimmed)}`);
      onNavigate?.();
    },
    [closeList, router, onNavigate],
  );

  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const next = e.target.value;
    setValue(next);
    scheduleSuggest(next);
  };

  const selectItem = (item: SuggestItem) => {
    setValue(item.name);
    goToSearch(item.name);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      if (items.length === 0) return;
      e.preventDefault();
      setOpen(true);
      setActiveIndex((i) => (i + 1 >= items.length ? 0 : i + 1));
      return;
    }
    if (e.key === "ArrowUp") {
      if (items.length === 0) return;
      e.preventDefault();
      setOpen(true);
      setActiveIndex((i) => (i - 1 < 0 ? items.length - 1 : i - 1));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (open && activeIndex >= 0 && items[activeIndex]) {
        selectItem(items[activeIndex]);
      } else {
        goToSearch(value);
      }
      return;
    }
    if (e.key === "Escape") {
      if (open) {
        e.preventDefault();
        // 候補だけを閉じる。伝播を止めないと、囲みの SearchPanel 自身の Escape ハンドラ
        // （AllMenu と同じパターン）まで同じキー入力で発火し、候補と一緒にパネルごと
        // 閉じてしまう（1 回の Escape で 2 段階の意図が同時に実行される不具合になる）
        e.stopPropagation();
        closeList();
      } else {
        onEscape?.();
      }
    }
  };

  const activeId = activeIndex >= 0 ? `${listboxId}-opt-${activeIndex}` : undefined;

  return (
    <div className={`relative ${className}`}>
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          if (open && activeIndex >= 0 && items[activeIndex]) {
            selectItem(items[activeIndex]);
          } else {
            goToSearch(value);
          }
        }}
      >
        <label htmlFor={`${listboxId}-input`} className="sr-only">
          商品を検索
        </label>
        <input
          ref={inputRef}
          id={`${listboxId}-input`}
          type="search"
          role="combobox"
          value={value}
          onChange={onChange}
          onKeyDown={onKeyDown}
          onBlur={() => {
            // 候補クリックは onMouseDown で先に処理するため、blur では単純に閉じてよい
            closeList();
          }}
          placeholder={placeholder}
          maxLength={100}
          autoComplete="off"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          className={`h-11 w-full rounded-sm border border-line bg-bg px-4 text-sm text-fg placeholder:text-fg-muted focus:border-fg focus:outline-none ${inputClassName}`}
        />
      </form>
      {open && items.length > 0 && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label="検索候補"
          className="absolute left-0 right-0 top-full z-50 mt-1 max-h-72 overflow-y-auto rounded-sm border border-line bg-bg shadow-modal"
        >
          {items.map((item, i) => (
            <li
              key={item.id}
              id={`${listboxId}-opt-${i}`}
              role="option"
              aria-selected={i === activeIndex}
              onMouseDown={(e) => {
                // input の blur より先に選択を確定させる
                e.preventDefault();
                selectItem(item);
              }}
              onMouseEnter={() => setActiveIndex(i)}
              className={`cursor-pointer px-4 py-2 text-sm text-fg ${i === activeIndex ? "bg-line" : ""}`}
            >
              {item.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
