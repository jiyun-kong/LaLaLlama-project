# main.py

import os
import asyncio
import json
from dotenv import load_dotenv
from crewai import Agent, Task, Crew
from crewai.llm import LLM

load_dotenv()

# --- LLM 정의 ---
# llm = LLM(
#     model="huggingface/meta-llama/Meta-Llama-3-8B-Instruct",
#     api_key=os.getenv("HUGGINGFACEHUB_API_TOKEN")
# )

llm = LLM(
    model="ollama/llama3.2",
    base_url="http://localhost:11434"
)


# --- RAG 함수 정의 ---
def get_context_for_topic(proposal_file, topic):
    print(f"INFO: '{proposal_file}'에서 '{topic}'에 대한 RAG 검색 중...")
    return f"'{proposal_file}'의 '{topic}' 관련 내용입니다. (가상 RAG 결과)"

async def main():
    print("## 동적 Agent 생성 및 평가 프로세스를 시작합니다.")

    # 전체 심사 항목 리스트 (어떤 대분류가 들어올지 모름)
    unstructured_evaluation_items = [
        {"대분류": "기술", "topic": "시스템 아키텍처", "criteria": "MSA 기반의 유연하고 확장 가능한 아키텍처인가?"},
        {"대분류": "관리", "topic": "프로젝트 관리 방안", "criteria": "WBS 기반의 상세하고 실현 가능한 일정을 제시하였는가?"},
        {"대분류": "기술", "topic": "데이터베이스 암호화", "criteria": "개인정보보호 및 데이터 암호화 방안이 명시되었는가?"},
        {"대분류": "관리", "topic": "투입 인력 계획", "criteria": "투입 인력의 역할과 경력이 적절한가?"},
        {"대분류": "가격", "topic": "비용 산정 내역", "criteria": "제시된 비용이 합리적이고 구체적인 근거를 포함하는가?"},
    ]

    # =================================================================
    # Phase 1: Dispatcher가 대분류를 스스로 찾아내고 항목 분류
    # =================================================================
    print("\n--- [Phase 1] Dispatcher Agent가 대분류를 식별하고 항목을 분류합니다 ---")
    
    dispatcher_agent = Agent(
        role="평가 항목 자동 분류 및 그룹화 전문가",
        goal="주어진 심사 항목 리스트에서 '대분류'를 기준으로 모든 항목을 그룹화하여 JSON으로 반환",
        backstory="당신은 복잡한 목록을 받아서 주요 카테고리별로 깔끔하게 정리하고 구조화하는 데 매우 뛰어난 능력을 가졌습니다.",
        llm=llm,
        verbose=True
    )

    items_as_string = json.dumps(unstructured_evaluation_items, ensure_ascii=False)
    
    dispatcher_task = Task(
        description=f"""아래 심사 항목 리스트를 분석하여 '대분류' 키 값을 기준으로 그룹화해주세요.
        
        [전체 심사 항목 리스트]
        {items_as_string}

        결과 JSON의 key는 리스트에 존재하는 '대분류'의 이름이어야 합니다.
        예를 들어, 대분류가 '기술'과 '관리'만 있다면 결과는 다음과 같아야 합니다.
        {{
          "기술": [{{'대분류':'기술', ...}}, ...],
          "관리": [{{'대분류':'관리', ...}}, ...]
        }}
        """,
        expected_output="JSON 객체. 각 key는 심사 항목 리스트에 있던 '대분류'이며, value는 해당 대분류에 속하는 항목 객체들의 리스트입니다.",
        agent=dispatcher_agent
    )

    dispatcher_crew = Crew(agents=[dispatcher_agent], tasks=[dispatcher_task], verbose=False)
    categorization_result = dispatcher_crew.kickoff()

    try:
        categorized_items = json.loads(categorization_result.raw)
        print("✅ 항목 분류 완료. 발견된 대분류:")
        for category, items in categorized_items.items():
            print(f"  - {category}: {len(items)}개 항목")
    except json.JSONDecodeError:
        print("❌ 항목 분류 실패!")
        categorized_items = {}


    # =================================================================
    # Phase 2: 대분류 개수만큼 동적으로 Agent를 생성하고 병렬 평가
    # =================================================================
    print("\n--- [Phase 2] 발견된 대분류별로 전문가 Agent를 동적으로 생성하여 병렬 평가합니다 ---")
    
    specialist_agents = []
    evaluation_tasks = []

    # 1. 분류된 결과(딕셔너리)를 순회하며 대분류별로 Agent와 Task를 생성
    for category, items in categorized_items.items():
        
        # 2. 해당 대분류를 위한 전문가 Agent 동적 생성
        specialist_agent = Agent(
            role=f"'{category}' 부문 전문 평가관",
            goal=f"제안서의 '{category}' 부문에 해당하는 모든 심사 항목들을 전문적으로 평가",
            backstory=f"당신은 오직 '{category}' 분야의 평가만을 위해 투입된 최고의 전문가입니다.",
            llm=llm,
            verbose=True
        )
        specialist_agents.append(specialist_agent)

        # 3. 해당 전문가가 수행할 Task들을 생성
        for item in items:
            context = get_context_for_topic("A사_제안서.pdf", item['topic'])
            task = Task(
                description=f"'{category}' 부문의 '{item['topic']}' 항목을 평가하시오.\n- 심사 기준: {item['criteria']}\n- 관련 내용: {context}",
                expected_output=f"'{item['topic']}'에 대한 평가 점수, 요약문, 근거가 포함된 평가 보고서",
                agent=specialist_agent # 👈 방금 생성한 해당 분야 전문가에게 할당
            )
            evaluation_tasks.append(task)

    # 4. 동적으로 생성된 모든 전문가와 Task들로 최종 평가 Crew 구성 및 실행
    if evaluation_tasks:
        evaluation_crew = Crew(
            agents=specialist_agents, # 동적으로 생성된 Agent 리스트
            tasks=evaluation_tasks,   # 동적으로 생성된 Task 리스트
            verbose=True
        )
        final_results = await evaluation_crew.kickoff_async()
        
        # ... (Phase 3: 보고서 작성 부분은 이전 코드와 동일하게 사용) ...
        print("\n\n--- [Phase 2] 개별 평가 완료 ---")
        individual_reports = "\n\n".join([str(result) for result in final_results])

        print("\n--- [Phase 3] Reporting Agent가 최종 보고서를 작성합니다 ---")
        reporting_agent = Agent(
            role="수석 평가 분석가 (Chief Evaluation Analyst)",
            goal="여러 개의 개별 평가 보고서를 종합하여, 경영진이 의사결정을 내릴 수 있도록 하나의 완성된 최종 보고서를 작성",
            backstory="당신은 여러 부서의 보고를 취합하여 핵심만 요약하고, 전체적인 관점에서 강점과 약점을 분석하여 최종 보고서를 작성하는 데 매우 능숙합니다.",
            llm=llm, verbose=True
        )
        reporting_task = Task(
            description=f"아래는 각 분야 전문가들이 작성한 개별 평가 보고서들입니다.\n\n[개별 평가 보고서 목록]\n{individual_reports}\n\n위 보고서들을 모두 종합하여, 제안서 전체에 대한 최종 평가 보고서를 작성해주세요...",
            expected_output="하나의 완성된 최종 평가 보고서",
            agent=reporting_agent
        )
        reporting_crew = Crew(agents=[reporting_agent], tasks=[reporting_task], verbose=False)
        final_comprehensive_report = reporting_crew.kickoff()

        print("\n\n🚀 최종 종합 평가 보고서\n==========================================")
        print(final_comprehensive_report.raw)
    else:
        print("평가할 작업이 없습니다.")

if __name__ == '__main__':
    asyncio.run(main())