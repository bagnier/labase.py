update public.profiles set display_name = email where display_name is null;

do $$
begin
  update test.profiles set display_name = email where display_name is null;
exception when undefined_table then null;
end;
$$;
