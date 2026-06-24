BEGIN;

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.message_citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.retrieval_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_permissions ENABLE ROW LEVEL SECURITY;

CREATE POLICY profiles_select_own
  ON public.profiles
  FOR SELECT
  USING (id = public.current_app_user_id());

CREATE POLICY profiles_insert_own
  ON public.profiles
  FOR INSERT
  WITH CHECK (id = public.current_app_user_id());

CREATE POLICY profiles_update_own
  ON public.profiles
  FOR UPDATE
  USING (id = public.current_app_user_id())
  WITH CHECK (id = public.current_app_user_id());

CREATE POLICY documents_select_owner_or_permitted
  ON public.documents
  FOR SELECT
  USING (
    user_id = public.current_app_user_id()
    OR EXISTS (
      SELECT 1
      FROM public.document_permissions AS dp
      WHERE dp.document_id = documents.id
        AND dp.permitted_user_id = public.current_app_user_id()
        AND dp.permission_level = 'read'
    )
  );

CREATE POLICY documents_insert_own
  ON public.documents
  FOR INSERT
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY documents_update_own
  ON public.documents
  FOR UPDATE
  USING (user_id = public.current_app_user_id())
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY documents_delete_own
  ON public.documents
  FOR DELETE
  USING (user_id = public.current_app_user_id());

CREATE POLICY document_chunks_select_owner_or_permitted
  ON public.document_chunks
  FOR SELECT
  USING (
    user_id = public.current_app_user_id()
    OR EXISTS (
      SELECT 1
      FROM public.document_permissions AS dp
      WHERE dp.document_id = document_chunks.document_id
        AND dp.permitted_user_id = public.current_app_user_id()
        AND dp.permission_level = 'read'
    )
  );

CREATE POLICY document_chunks_insert_own
  ON public.document_chunks
  FOR INSERT
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY document_chunks_update_own
  ON public.document_chunks
  FOR UPDATE
  USING (user_id = public.current_app_user_id())
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY document_chunks_delete_own
  ON public.document_chunks
  FOR DELETE
  USING (user_id = public.current_app_user_id());

CREATE POLICY chat_sessions_select_own
  ON public.chat_sessions
  FOR SELECT
  USING (user_id = public.current_app_user_id());

CREATE POLICY chat_sessions_insert_own
  ON public.chat_sessions
  FOR INSERT
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY chat_sessions_update_own
  ON public.chat_sessions
  FOR UPDATE
  USING (user_id = public.current_app_user_id())
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY chat_sessions_delete_own
  ON public.chat_sessions
  FOR DELETE
  USING (user_id = public.current_app_user_id());

CREATE POLICY chat_messages_select_own
  ON public.chat_messages
  FOR SELECT
  USING (user_id = public.current_app_user_id());

CREATE POLICY chat_messages_insert_own
  ON public.chat_messages
  FOR INSERT
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY chat_messages_update_own
  ON public.chat_messages
  FOR UPDATE
  USING (user_id = public.current_app_user_id())
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY chat_messages_delete_own
  ON public.chat_messages
  FOR DELETE
  USING (user_id = public.current_app_user_id());

CREATE POLICY message_citations_select_via_owned_message
  ON public.message_citations
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.chat_messages AS cm
      WHERE cm.id = message_citations.message_id
        AND cm.user_id = public.current_app_user_id()
    )
  );

CREATE POLICY message_citations_insert_via_owned_message
  ON public.message_citations
  FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.chat_messages AS cm
      WHERE cm.id = message_citations.message_id
        AND cm.user_id = public.current_app_user_id()
    )
  );

CREATE POLICY message_citations_delete_via_owned_message
  ON public.message_citations
  FOR DELETE
  USING (
    EXISTS (
      SELECT 1
      FROM public.chat_messages AS cm
      WHERE cm.id = message_citations.message_id
        AND cm.user_id = public.current_app_user_id()
    )
  );

CREATE POLICY retrieval_logs_select_own
  ON public.retrieval_logs
  FOR SELECT
  USING (user_id = public.current_app_user_id());

CREATE POLICY retrieval_logs_insert_own
  ON public.retrieval_logs
  FOR INSERT
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY feedback_select_own
  ON public.feedback
  FOR SELECT
  USING (user_id = public.current_app_user_id());

CREATE POLICY feedback_insert_own
  ON public.feedback
  FOR INSERT
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY feedback_update_own
  ON public.feedback
  FOR UPDATE
  USING (user_id = public.current_app_user_id())
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY feedback_delete_own
  ON public.feedback
  FOR DELETE
  USING (user_id = public.current_app_user_id());

CREATE POLICY audit_logs_select_own
  ON public.audit_logs
  FOR SELECT
  USING (user_id = public.current_app_user_id());

CREATE POLICY audit_logs_insert_own
  ON public.audit_logs
  FOR INSERT
  WITH CHECK (user_id = public.current_app_user_id());

CREATE POLICY document_permissions_select_owner_or_permitted
  ON public.document_permissions
  FOR SELECT
  USING (
    owner_user_id = public.current_app_user_id()
    OR permitted_user_id = public.current_app_user_id()
  );

CREATE POLICY document_permissions_insert_owner
  ON public.document_permissions
  FOR INSERT
  WITH CHECK (owner_user_id = public.current_app_user_id());

CREATE POLICY document_permissions_update_owner
  ON public.document_permissions
  FOR UPDATE
  USING (owner_user_id = public.current_app_user_id())
  WITH CHECK (owner_user_id = public.current_app_user_id());

CREATE POLICY document_permissions_delete_owner
  ON public.document_permissions
  FOR DELETE
  USING (owner_user_id = public.current_app_user_id());

COMMIT;

